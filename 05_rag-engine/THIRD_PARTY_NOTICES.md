# Third-Party Notices and Research Record

Research date: 2026-09-04.  
Closure verification: 2026-09-05.  
No complete third-party repository or source file was copied into this module.

| Project | Repository / documentation | Version or revision observed | License | Purpose | Integration type | Source copied? | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| FlagEmbedding | [FlagOpen/FlagEmbedding](https://github.com/FlagOpen/FlagEmbedding) | package 1.4.2; `main` `fd1a2bdf69488ffebe0327999d4400d8c8058a0b` | MIT | BGE-M3 dense/learned sparse and BGE reranker adapters | Runtime adapter | No | Studied `examples/inference/embedder/README.md`, `examples/inference/embedder/encoder_only/m3_single_device.py`, `research/BGE_M3/README.md`, and `examples/inference/reranker/README.md`. Current examples expose `BGEM3FlagModel`, `encode_queries`, `encode_corpus`, lexical weights, and `FlagAutoReranker`. |
| BAAI/bge-m3 | [Hugging Face model card](https://huggingface.co/BAAI/bge-m3) | snapshot `5617a9f61b028005a4858fdac845db406aefb181` | Model-specific terms | 1024-dimensional multilingual embedding model | Downloaded runtime asset | No | Weights are outside Git and use the configured Hugging Face cache. |
| BAAI/bge-reranker-v2-m3 | [Hugging Face model card](https://huggingface.co/BAAI/bge-reranker-v2-m3) | snapshot `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`; `model.safetensors` SHA-256 `d9e3e081faff1eefb84019509b2f5558fd74c1a05a2c7db22f74174fcedb5286` | Apache-2.0 | Multilingual cross-encoder reranker | Downloaded runtime asset | No | Official Hugging Face source; weight file 2,271,071,852 bytes; cache is `D:\Dev\caches\huggingface`; weights are not committed. |
| Chroma | [chroma-core/chroma](https://github.com/chroma-core/chroma) and [usage guide](https://github.com/chroma-core/docs/blob/main/docs/usage-guide.md) | package 1.5.9; `main` `34f8e76bae6195b91160e78b2e47a397055aa3b` | Apache-2.0 | Required local dense HNSW baseline | Direct Python client through `ChromaVectorStore` | No | Studied `PersistentClient`, collection metadata `hnsw:space=cosine`, explicit `query_embeddings`, and `where` metadata filtering. |
| Qdrant | [qdrant/qdrant](https://github.com/qdrant/qdrant) and [hybrid query docs](https://qdrant.tech/documentation/search/hybrid-queries/) | package 1.19.0; repository `main` `6ab21cac18ebb6f4ae29102c7f8f5cc11affd5de` | Apache-2.0 | Advanced dense/sparse named-vector and hybrid PoC | Direct local Python client through `QdrantVectorStore` | No | Studied local persistent mode, payload filters, `query_points`, prefetch, and native RRF. |
| BM25S | [xhluca/bm25s](https://github.com/xhluca/bm25s) | package 0.3.11; repository `main` `a213158181d4b3781ba06bc88840f89871f1c775` | MIT | Classical lexical retrieval baseline | Direct Python library through `BM25SRetriever` | No | Studied `tokenize`, `BM25.index`, `retrieve`, `save`, `load`, and the `Tokenizer` extension point. |
| RAGFlow | [infiniflow/ragflow](https://github.com/infiniflow/ragflow) | `main` `f99b9cd44b00f99dc79537ecdad710c5d693c902` | Apache-2.0 | Retrieval architecture reference | Research/reference only | No | Studied `agent/tools/retrieval.py`, `common/metadata_utils.py`, `rag/llm/rerank_model.py`, `api/apps/restful_apis/search_api.py`, `docs/guides/search/search_settings.md`, and `rag/prompts/citation_prompt.md`. Adopted explicit candidate/rerank limits, metadata filtering, and citation ordering ideas; no RAGFlow runtime. |
| Haystack | [deepset-ai/haystack](https://github.com/deepset-ai/haystack) | package 3.1.1; `main` `c536c35a43d18c7574bd7a820ead74a80c17ed3e` | Apache-2.0 | Typed pipeline/component architecture reference | Research/reference only | No | Studied `haystack/core/pipeline/base.py`, `haystack/core/pipeline/pipeline.py`, component and retriever docs. No Haystack dependency is installed. |
| LlamaIndex | [run-llama/llama_index](https://github.com/run-llama/llama_index) | package 0.14.24; `HEAD` `d2ac544a27c73d2a68e9c57efec4b2ac0ef99892` | MIT | Retriever/router/metadata/citation architecture reference | Research/reference only | No | Metadata filter and citation concepts informed domain boundaries; no ingestion or runtime dependency. |
| Ragas | [explodinggradients/ragas](https://github.com/explodinggradients/ragas) | package 0.4.3; `main` `298b68274234c060deacab3cf5fb52aa3a20e885` | Apache-2.0 | Evaluation metric reference | Research/reference only | No | Studied context precision, context recall, faithfulness, and answer relevancy. Round 1 uses deterministic ID-based IR metrics instead of LLM judges. |

## License handling

The active runtime adapters use the upstream packages through their public
APIs. The module does not vendor their implementation. BGE-M3 and the
reranker have separate model-card terms that must be reviewed before any
production or redistribution use; Round 1 only uses synthetic fixtures.
