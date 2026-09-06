# OWASP SAFETY MAPPING

Scope: module-level engineering mapping for StudentMentalHealthAI Safety
Control Plane Round 1. This is an implementation mapping, not an OWASP
certification or a complete application security assessment.

Source checked 2026-09-05: OWASP GenAI LLM Top 10 2026
(https://genai.owasp.org/resource/owasp-genai-llm-top-10-2026/). The source
describes a current, community-driven risk guide with updated rankings,
expanded coverage, attack scenarios, mitigations, and mappings to NIST, MITRE
ATLAS, CWE, and agentic-application guidance. The controls below are scoped to
this module and should be rechecked when the application threat model changes.

| OWASP concern | Safety Engine control | Evidence | Residual risk |
|---|---|---|---|
| Prompt injection | Deterministic input/retrieval patterns, NeMo input IORails, Qwen input classification, OPA block priority, no raw retrieved instruction execution | service/rules.py, adapters/nemo, retrieval/adapter.py, OPA tests | Pattern and model evasion; defense in depth is not a solved problem |
| Sensitive information disclosure | Presidio detection/redaction, PII-safe signal/trace validators, role disclosure matrix, no full conversation metadata | adapters/presidio, domain/models.py, privacy/disclosure.py | Entity recall/precision varies by language and entity type |
| Improper or unsafe output handling | Candidate output is checked before returning; clinical boundary and NeMo output rails run before OPA | SafetyService.postcheck, integration tests | Downstream consumers must still enforce the decision |
| System prompt or policy leakage | Injection/jailbreak reason codes, deterministic blocking, no system prompt in any response model or trace | service/rules.py, SafetyTrace contract | Indirect leakage through external layers is outside this module |
| Supply-chain vulnerabilities | Pinned package versions, pinned Qwen revision, verified OPA SHA-256, third-party notices, no cloud guard dependency | pyproject.toml, runtime report, THIRD_PARTY_NOTICES.md | Transitive packages and future lock changes need review |
| Excessive agency | Safety service has no tools, no notification integration, no normal LLM client, and OPA only maps signals to actions | service/engine.py, frozen D-06/D-18 | Hosting or calling modules could add agency outside this boundary |
| Overreliance on model output | Qwen is one normalized signal; deterministic rules, Presidio, NeMo, OPA, review, and fail-closed semantics remain in the path | synthetic evaluation report | Small guard model is not a clinical or universal safety oracle |
| Vector/retrieval weakness | Retrieved chunks require approved review and verified rights; injection-like and PII checks run before consumption | retrieval/adapter.py, RETRIEVAL_INJECTION fixture | RAG ranking, embedding poisoning, and source provenance remain RAG-owned |
| Misinformation / sensitive context | Controversial model outputs become REVIEW_REQUIRED; no diagnostic or factual authority is asserted | Qwen adapter, OPA policy, clinical boundary | Content quality and clinical factuality require other review |
| Unbounded consumption / denial of service | Request and chunk limits in API models, component timeouts, local CPU gate recorded as non-production latency | api/app.py, config, runtime report | Full load and concurrency testing is not a Round 1 acceptance claim |

## Control interpretation

A Qwen label is normalized to an engineering signal:

- Safe contributes an observation and may proceed only when all mandatory
  components are healthy.
- Controversial requests human review.
- Unsafe blocks.
- A Qwen model failure creates a component-health signal and cannot silently
  proceed.

No OWASP row is interpreted as permission to calculate a clinical threshold or
to send an automatic guardian notification. Crisis routing remains an
explicitly marked synthetic engineering route pending psychology review.

## Out of scope

The mapping does not cover identity and access management, host hardening,
network segmentation beyond loopback OPA binding, secret management, CI
signing, data deletion law, or a production red-team assessment. Those require
a project-level security review and, where needed, a change request outside
this module.

