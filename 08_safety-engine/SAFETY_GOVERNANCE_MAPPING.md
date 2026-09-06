# SAFETY GOVERNANCE MAPPING

This document maps the Round 1 Safety Control Plane to public governance
guidance. It is evidence of design intent and implementation coverage, not a
legal compliance determination or clinical validation.

Sources checked 2026-09-05:

- NIST AI RMF: https://www.nist.gov/itl/ai-risk-management-framework
- NIST Generative AI Profile: https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf
- WHO Ethics and Governance of AI for Health:
  https://www.who.int/publications/i/item/9789240029200
- UNICEF Guidance on AI and Children 3.0:
  https://www.unicef.org/innocenti/reports/policy-guidance-ai-children

## NIST AI RMF

| Function | Module interpretation | Evidence / status |
|---|---|---|
| Govern | Frozen decisions, ownership, role disclosure, no automatic notification, explicit non-clinical boundary, third-party notices | D-01..D-30; implemented |
| Map | Threat and data-flow mapping across input, output, retrieval, crisis, and component failures | technical decision; implemented for Round 1 scope |
| Measure | Synthetic fixtures, actual model outputs, component latency, source signal IDs, OPA/NeMo/Presidio gates | evaluation harness; implemented, not a clinical measure |
| Manage | OPA action vocabulary, fail-closed behavior, deterministic crisis template, human review transitions | service, policies, review repository; implemented |

The NIST profile is used as a risk-management reference. The module does not
claim that its implementation alone satisfies the profile or any regulatory
obligation.

## WHO ethics and governance for AI for health

| WHO-oriented principle | Module response | Boundary |
|---|---|---|
| Protect autonomy | No diagnosis, treatment decision, or hidden clinical score; action is an engineering control | Clinical decision support requires separate approved work |
| Promote well-being and safety | Layered privacy, guardrails, model, policy, review, and crisis route | Templates are not emergency guidance |
| Ensure transparency, explainability, and intelligibility | Reason codes, source signal IDs, policy/service versions, PII-safe traces | Raw content is intentionally not included |
| Foster responsibility and accountability | Named owner, review case, audit events, no automatic guardian notification | Organizational accountability remains with project governance |
| Ensure inclusiveness and equity | Chinese synthetic PII recognizers and child/adolescent age group are explicit evaluation dimensions | No fairness or clinical performance claim |
| Promote AI that is responsive and sustainable | Local-first, CPU-compatible gate, no cloud provider, component health and failure states | CPU throughput is not a production SLO |

## UNICEF AI and children guidance

The project concerns students, so the relevant child-centered requirements are
treated as design constraints:

1. Oversight and compliance: review cases and frozen decisions exist; local
   legal/child-safety review remains required.
2. Safety: unsafe content, injection, component failures, and explicit synthetic
   crisis signals cannot silently proceed.
3. Privacy: Presidio redacts synthetic PII; traces reject raw sensitive keys.
4. Fairness: the Round 1 fixture set is not evidence of fairness; a reviewed
   multilingual benchmark remains a blocker for stronger claims.
5. Transparency and accountability: versioned decisions and auditable
   transitions are exposed internally.
6. Rights and responsible practice: no diagnosis, treatment, or coercive
   automatic escalation is implemented.
7. Best interests, development, and well-being: adolescent context is
   explicit, while templates remain pending psychology review.
8. Inclusion: English and Chinese synthetic entity patterns are included; more
   languages are not implied.
9. Preparation and skills: not a Round 1 feature; no student-facing
   educational claim is made by the Safety Engine.
10. Enabling environment: local-only operation, no real student data, and a
    documented path for future expert review.

## Governance gaps requiring later approval

- Psychology/clinical review of crisis templates and any future real-world
  crisis workflow.
- Child-rights, privacy, and local legal review before real student data.
- A reviewed multilingual PII and safety benchmark with false-positive and
  false-negative analysis.
- Operational ownership for human reviewers and any future notification policy.
- Security review of deployment, secrets, access control, and supply-chain
  update policy.

