# Runtime Decision Fidelity Reconciliation — R1

Date: 2026-09-07  
Decision source: `RUNTIME_SERVICE_TECHNICAL_DECISION_V1.md`  
Register: `RTS-01..RTS-52`

## Materialization

The Controller-frozen register is present in the technical decision document in
the original numbering and substance. The closure count is:

```text
Controller register = RTS-01..RTS-52
materialized = 52/52
semantic deviations = 0
```

The register was checked for one occurrence of each identifier from RTS-01
through RTS-52 and for no missing or duplicate identifier. Supplementary
compatibility decisions appear after the register as permitted by the source
instruction.

## Semantic reconciliation

| Decision area | Closure result |
|---|---|
| Provenance and baseline | Reconstruction is explicitly distinguished from historical restoration; baseline tag and independent worktree are recorded. |
| Provider/model boundaries | Existing Ollama adapter remains the protocol boundary; ProviderRegistry and ModelRegistry are separate and explicit. |
| Retry/fallback | Operational pre-output retry is bounded; structured validation, safety/policy, invalid request, and post-output failures do not silently fallback. |
| HTTP/lifecycle | One RuntimeService is owned by FastAPI lifespan; local clients are pooled, finite-timeout, and `trust_env=false`. |
| Process ownership | EXTERNAL and MANAGED are explicit; only verified owned trees are stopped, with no broad image-name kill. |
| Structured output | Native JSON Schema plus canonical Pydantic validation; no fence/prose repair; thinking is not surfaced as product content. |
| Product boundary | Results are buffered before downstream Safety; provider streaming is internal and raw tokens do not cross the browser boundary. |
| Scope boundary | Root Contract, Backend, Safety, RAG, Database, and Frontend source remain unchanged; evidence uses synthetic data only. |

The conflict register records twelve source/evidence conflicts and their
resolutions. The current closure adds live evidence for the previously
execution-sensitive GPU and Backend compatibility decisions; no P0 semantic
conflict remains.
