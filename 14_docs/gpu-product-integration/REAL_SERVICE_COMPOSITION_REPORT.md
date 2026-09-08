# Real Service Composition Report

## Final disposition

The final live run used the real product composition and ended `PARTIAL_PASS`. No ContractFake was used in the product path. The normal hard gate remains open because the accepted publication plus formal Qwen2.5 7B path returns invalid structured JSON.

## Runtime topology

| Layer | Endpoint / identity | Evidence |
| --- | --- | --- |
| Backend | `127.0.0.1:8080`, real FastAPI product | `service_composition_manifest.json`, `backend.out.log` |
| CAT | `127.0.0.1:8180`, `adaptivetesting-1.2.1` | CAT 24 passed; live CAT sessions completed with 8 items per fixture |
| RAG | `127.0.0.1:8170`, BGE-M3 + BM25S + RRF, reranker OFF | `synthetic_rag_boundary.json`, RAG 18 passed / 4 skipped |
| Safety | `127.0.0.1:8190`, Qwen3Guard + NeMo + Presidio + OPA | readiness all true; controlled fixture blocked |
| OPA | `127.0.0.1:8181`, 1.20.2 | live readiness and policy decision recorded |
| RuntimeService | `127.0.0.1:8160`, accepted RuntimeService + OllamaProvider | `runtime-service-primary.jsonl`, `runtime-service-fallback.jsonl` |
| GPU Ollama | dedicated `127.0.0.1:11435`, 0.33.3 | exact model/digest and `/api/ps` resource evidence |
| CPU fallback Ollama | dedicated `127.0.0.1:11436`, CPU AVX2 | fallback model `qwen2.5:1.5b`, VRAM 0 |
| Observers | CAT 8280, RAG 8270, LLM 8260, Safety 8290, Ollama 11535 | body-blind sanitized summaries only |
| MySQL | isolated 8.4.8 on port 3307 | migration head `20260906_0002`, synthetic database only |

## Product call paths

### Normal

The final run executed three CAT-complete normal fixtures. Each request reached real Input Safety, real RAG and the real RuntimeService/Ollama GPU boundary. The dedicated Ollama endpoint returned HTTP 200, but RuntimeService rejected the provider response as `INVALID_STRUCTURED_OUTPUT` at JSON line 26, column 9. Backend returned HTTP 502 for all three. No normal content or citation round trip can be accepted from these responses.

### Crisis

All three crisis fixtures passed. Input Safety returned `CRISIS_ROUTE`; the call matrix recorded zero normal RAG calls, zero Runtime generation calls, zero Ollama generation calls and zero GPU generation calls. No normal content or citations were persisted.

### Controlled Output Safety

The real Output Safety path blocked the accepted `PROMPT_INJECTION` fixture with decision `BLOCK`. The backend controlled flow delivered no content, used `generation_status=NOT_RUN`, and persisted zero blocked approved-output messages.

### Safety-down

Two requests while the real Safety service was unavailable returned HTTP 503 and failed closed. Both recorded zero RAG, Runtime and Ollama generation calls. Safety was restored before fallback testing.

### Product fallback

All three fallback fixtures passed through Backend, real RAG, RuntimeService, local CPU Ollama, real Output Safety and MySQL. The primary model was made unavailable through an acceptance-only provider-model injection. RuntimeService recorded `fallback_used=true`, primary `MODEL_NOT_FOUND`, and the actual fallback `qwen2.5:1.5b` with digest `65ec06548149b04c096a120e4a6da9d4017ea809c91734ea5631e89f96ddc57b`. Resource evidence recorded fallback `size_vram=0` and device `CPU`; cloud calls were zero.

## Persistence and cleanup

The isolated database recorded 4 accounts, 2 subjects, 10 assessment sessions, 12 support sessions, 12 support runs, 15 support evidence rows, 7 Safety decisions and 3 review cases. It recorded 15 support messages, 3 approved output messages, 0 blocked approved-output messages and 0 crisis approved-output messages. Sensitive message fields were encrypted. All owned service PIDs were explicitly cleaned, and the acceptance ports were free after the run.

## Boundary conclusion

The service composition is real and the non-normal hard gates are evidenced. The unresolved issue is a product-level structured-output incompatibility at the exact accepted RAG boundary, documented in [PRODUCT_INTEGRATION_BLOCKER.md](PRODUCT_INTEGRATION_BLOCKER.md). No source-level workaround was applied.
