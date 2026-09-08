# GPU Product Integration Technical Decision V1.1 — Controller Correction

Status: **FROZEN — CONTROLLER CORRECTION**

The previous agent-generated technical decision is retained as historical
partial-round evidence. This document restores the authoritative Controller
numbering without changing product behavior.

## Authoritative GPI Register

### GPI-01

Formal source baseline = RuntimeService accepted commit
`2972be77e537ef03033332039a6ed0eed8e451ef`.

### GPI-02

Use an independent branch/worktree.

### GPI-03

Do not merge D1, D2 or Frontend experimental branches.

### GPI-04

Use the accepted synthetic Knowledge Round 1 boundary, not the unaccepted D2
candidate.

### GPI-05

Full-real composition = Backend + CAT + RAG + Runtime + Ollama + Safety + OPA +
MySQL.

### GPI-06

Frontend/browser is not a C hard gate.

### GPI-07

Capability services remain loopback-only.

### GPI-08

RTX3060 is owned only by LLM Runtime.

### GPI-09

CAT/RAG/Safety/OPA/Backend remain CPU-owned.

### GPI-10

`cloud_fallback = false`.

### GPI-11

GPU Runtime = Ollama 0.33.3.

### GPI-12

Primary model = `qwen2.5:7b-instruct-q4_K_M` with exact accepted digest.

### GPI-13

Primary runtime parameters = context 8192 / KV f16 / parallel 1.

### GPI-14

Input Safety executes before normal RAG/LLM.

### GPI-15

`CRISIS_ROUTE` bypasses normal RAG.

### GPI-16

`CRISIS_ROUTE` RuntimeService generation calls = 0.

### GPI-17

`CRISIS_ROUTE` Ollama/GPU generation calls = 0.

### GPI-18

Normal path requires real RAG evidence; no silent ungrounded generation.

### GPI-19

Full-real flows prohibit ContractFake.

### GPI-20

Product generation remains buffered.

### GPI-21

Raw Ollama tokens are never delivered directly to Browser/Student.

### GPI-22

Output Safety executes before product delivery.

### GPI-23

Output Safety block/failure prevents candidate delivery.

### GPI-24

Unsafe candidate is not persisted as approved/full output.

### GPI-25

Safety unavailable = fail closed.

### GPI-26

If Input Safety is unavailable before generation, normal RAG/LLM must not run.

### GPI-27

OPA unavailable/undefined must not become allow.

### GPI-28

Real Safety requires accepted Presidio + NeMo + Qwen3Guard + OPA readiness.

### GPI-29

Do not migrate to Qwen3Guard-Stream in this Closure.

### GPI-30

Do not introduce new NeMo Retrieval Rail.

### GPI-31

Normal full-real = 3/3.

### GPI-32

Crisis full-real = 3/3.

### GPI-33

All Normal real GPU candidates must pass real Output Safety.

### GPI-34

Controlled unsafe candidate separately verifies real Output Safety block/review.

### GPI-35

Controlled unsafe test must not be represented as Full-Real GPU Normal flow.

### GPI-36

Safety-down >= 2/2 fail-closed.

### GPI-37

Product fallback must pass through accepted RuntimeService.

### GPI-38

Fallback target must be an explicit local model.

### GPI-39

Fallback must prove cloud calls = 0.

### GPI-40

Fallback product path still requires real Output Safety.

### GPI-41

Full-real MySQL uses a fresh isolated synthetic test database.

### GPI-42

Normal citation identity must survive: RAG → Backend → persistence/report.

### GPI-43

Crisis must not create normal citations/content.

### GPI-44

Output-unsafe / Safety-down must not persist rejected candidate as approved
output.

### GPI-45

Use existing request/trace correlation; do not introduce OpenTelemetry
infrastructure for this Closure.

### GPI-46

Acceptance-only call-count observers are allowed only if they do not modify
service behavior.

### GPI-47

All required real services must pass readiness before flows.

### GPI-48

All owned test processes must be cleaned without killing unrelated user
processes.

### GPI-49

Root/Frozen/accepted module regressions must remain green.

### GPI-50

Agent has no ACCEPTED/tag/merge/push authority; Controller performs final
acceptance.

## Correction Boundary

Authoritative GPI total: **50**. The previous misnumbered document remains
unchanged as historical evidence. This correction does not authorize acceptance,
merge, push, or an accepted tag.
