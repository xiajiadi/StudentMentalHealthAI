# SAFETY TECHNICAL DECISION V1

| Field | Value |
|---|---|
| Project | StudentMentalHealthAI |
| Module | Safety Control Plane (08_safety-engine) |
| Version | 1.0 |
| Status | PROVISIONALLY_FROZEN |
| Date | 2026-09-05 |
| Depends | Root Contract v0.1.0 FROZEN |
| Owner | Project Technical Lead |
| Data boundary | Synthetic/de-identified fixtures only; no real student data in Round 1 |

This document is the module-level technical decision record for Round 1. It is
an internal engineering control design, not a clinical protocol, diagnostic
instrument, emergency response procedure, or statement of clinical validity.
The root contracts and root OpenAPI document remain unchanged.

## Frozen decisions

The following decisions are provisionally frozen for Round 1. A change requires
a new decision record or an explicit technical-lead approval.

| ID | Decision | Round 1 consequence |
|---|---|---|
| D-01 | Safety is an independent Safety Control Plane/service, not an output filter. | Input, output, retrieval, review, crisis, policy, and trace concerns live behind this module boundary. |
| D-02 | The service is isolated from the normal LLM Runtime. | No project-wide LLM gateway, provider registry, or safety bypass is added here. |
| D-03 | Runtime is Python 3.12 in a module-local virtual environment. | pyproject.toml requires >=3.12,<3.13; the verified interpreter is installed on D:. |
| D-04 | NeMo Guardrails is an internal orchestration SDK only. | NeMo types stop at adapters/nemo; no NeMo type enters a domain contract. |
| D-05 | Prefer the NeMo 0.24.x I/O API. | The implementation uses IORails.check_async() and the real RailType enum. |
| D-06 | NeMo is validation-only in this module. | No generate, main-model call, cloud model, or project-wide generation ownership is permitted. |
| D-07 | Qwen3Guard-Gen-0.6B is the Round 1 semantic guard. | The pinned model is Qwen/Qwen3Guard-Gen-0.6B at revision fada3b2f655b89601929198343c94cd2f64d93cc. |
| D-08 | Qwen3Guard-Stream is deferred. | Token-level streaming and GPU serving are DEFERRED_ROUND_2_GPU. |
| D-09 | Presidio is the primary PII engine. | Extend its recognizer registry; do not rebuild a parallel anonymization system. |
| D-10 | Chinese PII coverage is explicitly extended and evaluated. | Round 1 adds synthetic Chinese ID, mobile phone, email, and student-ID recognizers; recall/precision remain evaluation questions. |
| D-11 | OPA is mandatory in V0.1. | The decision must pass through a local OPA REST sidecar; a missing sidecar cannot become allow. |
| D-12 | OPA is deterministic and local. | OPA binds to loopback and converts normalized signals to actions only. |
| D-13 | OPA does not perform NLP or clinical work. | No diagnosis, psychometric calculation, theta/SE calculation, or clinical threshold is represented in Rego. |
| D-14 | Actions are engineering controls, not diagnoses. | The stable vocabulary is exactly PROCEED, PROCEED_WITH_BOUNDARY, BLOCK, REVIEW_REQUIRED, CRISIS_ROUTE. |
| D-15 | Crisis route has priority over ordinary signals. | An explicitly marked synthetic crisis signal overrides an upstream normal assessment signal. |
| D-16 | Crisis route bypasses normal free-form generation. | The response is a deterministic versioned template and the service has no normal LLM client. |
| D-17 | Round 1 crisis templates are placeholders. | Templates are PENDING_PSYCH_REVIEW, carry NOT CLINICALLY APPROVED, and contain no invented contact data. |
| D-18 | No automatic guardian notification is performed. | A review case is created; notification is always false in Round 1. |
| D-19 | Human review is mandatory for crisis and high-uncertainty controls. | The review state machine is persisted in memory or optional local SQLite. |
| D-20 | Review actors are synthetic in Round 1. | IDs must use the synthetic reviewer convention; no real reviewer identity is stored. |
| D-21 | No real student data is permitted in Round 1. | Fixtures and runtime probes are synthetic; the service config sets this boundary to false. |
| D-22 | Fail closed. | Policy, privacy, rail, guard-model, template, review, or service failures produce a non-PROCEED outcome. |
| D-23 | Decisions and traces are versioned and auditable. | Every decision carries policy version/revision, service version, trace ID, and source signal IDs. |
| D-24 | Sensitive content is absent from signals/traces by default. | Text may be digested for correlation; raw text, spans, and full conversation are rejected from metadata. |
| D-25 | Disclosure is role-aware. | Only FULL, SUMMARY, REDACTED, and HIDDEN are valid disclosure policies. PII causes a REDACTED override. |
| D-26 | Assessment signals are consumed, not recalculated. | Safety maps upstream observations into signals and does not calculate theta, SE, score, or clinical thresholds. |
| D-27 | Retrieval safety is a separate adapter. | It checks PII, injection-like content, and source eligibility; it does not implement RAG. |
| D-28 | Retrieval integration status is honest. | Because NeMo 0.24.x IORails does not expose a retrieval surface, the adapter reports PARTIAL. |
| D-29 | Real component gates are separate from unit tests. | Mock providers are allowed only for unit tests; the acceptance harness records actual component output or a blocker. |
| D-30 | Scope is module-only. | Root schemas, OpenAPI, MySQL, Assessment, RAG, and LLM Runtime files are not modified. Cross-module needs become a change request. |

## Control-plane shape

    SafetyContext
         |
         v
    Presidio privacy -> NeMo input IORails -> Qwen3Guard -> normalize signals
         |                                                         |
         +-----------------------------> OPA decision <------------+
                                                 |
                     +---------------------------+-------------------------+
                     |                           |                         |
                  proceed                   boundary/block            crisis route
                                                                             |
                                                         deterministic template + review case

Output checking is the same pattern with candidate text and output rails. The
retrieval adapter runs before retrieved content is consumed by another module;
it does not claim to be a NeMo retrieval rail.

## Internal contracts

### SafetySignal

Required fields are signal_id, source, signal_type, category,
severity_hint, confidence, reason_code, component,
component_version, timestamp, trace_id, and metadata. Sources include
ASSESSMENT, PRESIDIO, NEMO, QWEN3GUARD, DETERMINISTIC_RULE, and
SYSTEM_HEALTH.

The signal is an observation. severity_hint is an implementation hint for
policy ordering; it is not a suicide-risk category or clinical label.

### SafetyContext

The context contains trace_id, request_id, actor_role, age_group,
assessment_signals, current_user_message, conversation_metadata,
retrieval_metadata, generation_metadata, and component_health. Long
conversation history is not accepted as a default metadata field.

### SafetyDecision

The decision contains decision_id, action, reason_codes,
source_signal_ids, requires_human, crisis_template_id, review_case_id,
disclosure_policy, policy_version, policy_revision,
safety_service_version, trace_id, and timestamp. Its fixed
decision_type is ENGINEERING_CONTROL_DECISION.

### HumanReviewCase

The review record contains review_id/case_id aliases, a stable case ID,
decision/trace references, priority, status, role assignment, disclosure
policy, timestamps, reviewer and decision fields, synthetic reviewer IDs, and
append-only audit event IDs. It contains no raw student message and has no
notification side effect.

### SafetyTrace

The trace carries trace/request IDs, stage events, signal IDs, component
versions, policy version and optional OPA decision ID, action, review/crisis
references, per-stage latencies, and failure/degraded flags. Its signal list
contains IDs only; raw prompt, assessment, and response content is excluded.

### SafetyClient

Future callers use the JSON-only `SafetyClient` over loopback HTTP. The client
does not import NeMo, Qwen, Presidio, or OPA types and therefore preserves the
module boundary for the 09_backend integration.

### Error vocabulary

The stable operational errors are:

SAFETY_SERVICE_UNAVAILABLE, POLICY_ENGINE_UNAVAILABLE,
POLICY_EVALUATION_FAILED, GUARD_MODEL_UNAVAILABLE,
PRIVACY_ENGINE_UNAVAILABLE, GUARDRAIL_CHECK_FAILED,
INVALID_SAFETY_CONTEXT, REVIEW_QUEUE_FAILED,
CRISIS_TEMPLATE_UNAVAILABLE, and RETRIEVAL_SAFETY_CHECK_FAILED.

Stable signal reason codes include EXPLICIT_CRISIS_SIGNAL, CONTENT_UNSAFE,
CONTENT_CONTROVERSIAL, PII_DETECTED, PROMPT_INJECTION, JAILBREAK,
CLINICAL_OVERREACH, COMPONENT_UNAVAILABLE,
DISCLOSURE_RESTRICTED, and NO_BLOCKING_SIGNAL.

## Pipeline semantics

### Input / precheck

SafetyContext -> Presidio detect/redact -> deterministic instruction and
clinical-boundary checks -> NeMo input IORails -> Qwen3Guard input
classification -> normalized signals -> OPA -> SafetyDecision.

An explicitly marked synthetic crisis fixture may route deterministically after
privacy processing. It does not invoke the normal generation path.

### Output / postcheck

candidate -> Presidio leakage detect/redact -> NeMo output IORails -> Qwen3Guard
response classification -> clinical-boundary guard -> OPA -> action.

Blocked or review-required output is not returned as an approved candidate.
PII-bearing output can return only the redacted candidate under
PROCEED_WITH_BOUNDARY.

### Retrieval

retrieved chunks -> source eligibility -> Presidio -> prompt-injection-like
rules -> OPA -> action.

Source metadata must say review_status=approved and rights_status=verified.
The adapter does not add or modify RAG retrieval behavior.

## Crisis boundary

The deterministic crisis signal is intentionally narrow in Round 1: a fixture
must set synthetic_fixture=true and either
explicit_crisis_signal=true or use one approved synthetic phrase. This is not
a clinically validated suicide detector. A real-world crisis phrase is not
silently promoted to a clinical determination by this module.

The route selects a versioned template, sets CRISIS_ROUTE, creates a
HumanReviewCase in PENDING, and marks normal_llm_invoked=false. The
template repository rejects missing or malformed templates. No phone number,
guardian contact, emergency process, or external notification is invented.

## Governance and research basis

Research was checked against current official sources on 2026-09-05:

- NVIDIA NeMo Guardrails IORails: https://docs.nvidia.com/nemo/guardrails/guardrails-python-sdk/nemoguardrails/guardrails/iorails; rail outcomes: https://docs.nvidia.com/nemo/guardrails/configure-guardrails/actions/rail-outcomes; release notes: https://docs.nvidia.com/nemo/guardrails/about-nemo-guardrails-library/release-notes. The installed package is 0.24.0; the implementation uses validation-only I/O rails and records retrieval as partial.
- QwenLM Qwen3Guard repository: https://github.com/QwenLM/Qwen3Guard and pinned model card: https://huggingface.co/Qwen/Qwen3Guard-Gen-0.6B. The official format is Safety: Safe|Unsafe|Controversial plus categories; Stream is deferred.
- Microsoft Presidio analyzer: https://microsoft.github.io/presidio/analyzer/, anonymizer: https://microsoft.github.io/presidio/anonymizer/, and installation: https://microsoft.github.io/presidio/installation/. The installed analyzer/anonymizer line is 2.2.364.
- Open Policy Agent REST API: https://www.openpolicyagent.org/docs/rest-api, CLI: https://www.openpolicyagent.org/docs/cli, and decision logs: https://www.openpolicyagent.org/docs/management-decision-logs. The verified local Windows binary is v1.20.2.
- NIST AI RMF: https://www.nist.gov/itl/ai-risk-management-framework and NIST Generative AI Profile: https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf: govern, map, measure, and manage are reflected in versioned policy, evidence, and fail-closed controls.
- WHO Ethics and Governance of AI for Health: https://www.who.int/publications/i/item/9789240029200: human rights, accountability, inclusiveness, and responsible oversight support the human-review and no-diagnosis boundary.
- UNICEF Guidance on AI and Children 3.0: https://www.unicef.org/innocenti/reports/policy-guidance-ai-children: child safety, privacy, transparency, best interests, inclusion, and oversight inform the adolescent-first disclosure and data boundary.
- OWASP GenAI LLM Top 10 2026: https://genai.owasp.org/resource/owasp-genai-llm-top-10-2026/: prompt injection, sensitive information disclosure, improper output handling, supply-chain, overreliance, and unbounded consumption risks are addressed by layered checks, redaction, local pinning, and explicit review.
- Guardrails AI validator concepts: https://guardrailsai.com/guardrails/docs/concepts/validators: used as a comparison reference only; it is not a runtime dependency or substitute for the selected NeMo/OPA architecture.

## Known limitations

1. Qwen3Guard-Gen-0.6B is a safety classifier, not a clinical assessor. Its
   label is one signal; this module does not claim model-perfect recall or
   clinical sensitivity.
2. Chinese PII recognizers are synthetic Round 1 extensions and require a
   larger, reviewed, language-specific benchmark before production claims.
3. NeMo regex rails are deterministic input/output validation only. They are
   not a complete prompt-injection, jailbreak, or clinical-safety solution.
4. Retrieval safety is PARTIAL until a separately reviewed retrieval rail or
   equivalent evidence is available.
5. Crisis templates remain pending psychology review. No production crisis
   messaging or notification workflow is approved by this document.
6. CPU inference is usable for a gate but not a production latency commitment;
   Stream/GPU work is deferred to Round 2.
