# RAG Runtime Compatibility

Checked: `2026-09-04T18:00:35.877Z`

## Runtime

- Python: `3.14.6`
- Platform: `Windows-11-10.0.26200-SP0`
- Torch: `2.14.0+cpu`
- CUDA available: `False`
- Hugging Face cache: `D:\Dev\caches\huggingface`

## Packages

| Package | Installed version |
| --- | --- |
| FlagEmbedding | `1.4.2` |
| bm25s | `0.3.11` |
| chromadb | `1.5.9` |
| jsonschema | `4.26.0` |
| numpy | `2.5.2` |
| pytest | `8.4.2` |
| qdrant-client | `1.19.0` |

## Model/provider checks

```json
{
  "BGE reranker": {
    "cache_path": "D:\\Dev\\caches\\huggingface",
    "device": "cpu",
    "load_error": null,
    "load_latency_ms": 2742.6886999892304,
    "loaded": true,
    "model_id": "MODEL_bge_reranker_v2_m3",
    "model_name": "BAAI/bge-reranker-v2-m3",
    "model_revision": "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e",
    "model_version": "1.4.2",
    "package_version": "1.4.2",
    "precision": "fp32",
    "provider": "FlagEmbedding",
    "score_probe": {
      "latency_ms": 3112.1673000016017,
      "score": 1.6324578609783202e-05,
      "status": "ok"
    },
    "score_probe_latency_ms": 3112.1673000016017,
    "status": "ok"
  },
  "BGE-M3": {
    "cache_path": "D:\\Dev\\caches\\huggingface",
    "device": "cpu",
    "dimension": 1024,
    "load_error": null,
    "loaded": true,
    "model_id": "MODEL_bge_m3",
    "model_name": "BAAI/bge-m3",
    "model_revision": "5617a9f61b028005a4858fdac845db406aefb181",
    "model_version": "1.4.2",
    "package_version": "1.4.2",
    "precision": "fp32",
    "provider": "FlagEmbedding",
    "sparse_nonempty_rows_observed": 1,
    "sparse_output_observed": true,
    "sparse_output_requested": true,
    "sparse_terms_observed": 5,
    "status": "ok"
  },
  "BM25S": {
    "built": true,
    "count": 14,
    "manifest": {
      "chunk_count": 14,
      "config_hash": "sha256:5e925553a4dc5eff802f2bfa0e049e00bc9ce16d3f2971b0347121c67508474c",
      "corpus_version": "sha256:4553317e36b1064880df01643a3171f7937e0ec420ead380c5d6702f2396aad2",
      "eligible_chunk_ids": [
        "CHUNK_106197a3e73c227f2028",
        "CHUNK_10c1a30901fe3b68faa7",
        "CHUNK_3d2d02ba1c8fbc506665",
        "CHUNK_67b56abe21fe9860a26d",
        "CHUNK_73dea0ea11c13057ae5b",
        "CHUNK_81cfc83a8ee77e0d2fcc",
        "CHUNK_8a23f59abc838d8f66e0",
        "CHUNK_8f85f2c0472e21acd2fa",
        "CHUNK_aded0067f15377aa83e1",
        "CHUNK_b34d75824a36a99466fc",
        "CHUNK_bcbe71382652340b2249",
        "CHUNK_c3718c65fcf4151af391",
        "CHUNK_f4b8d47cca28f33baaf9",
        "CHUNK_fe0153fc5c3472e79982"
      ],
      "index_id": "INDEX_BM25_97e8943195627046fe1f898d",
      "index_version": "1.0.0",
      "provider": "bm25s",
      "provider_version": "0.3.11",
      "timestamp": "2026-09-04T17:56:45.359Z",
      "tokenizer_version": "cjk-bigram-v1"
    },
    "provider": "bm25s",
    "reused": true,
    "status": "ok",
    "version": "0.3.11"
  },
  "Mock Dense": {
    "device": "cpu",
    "dimension": 64,
    "loaded": true,
    "model_id": "MODEL_mock_embedding",
    "model_name": "deterministic-hash-embedding",
    "model_revision": "mock-deterministic-v1",
    "model_version": "mock-deterministic-v1",
    "precision": "fp32",
    "provider": "mock",
    "status": "ok",
    "test_only": true
  }
}
```

## Known warnings

- Windows does not support the Hugging Face cache symlink optimization; the cache remains valid but may use more disk space.
- The integration test run reports deprecation warnings from jsonschema.RefResolver and Chroma telemetry; they do not affect the recorded results.
- CUDA is unavailable on this host; GPU performance is not validated.
