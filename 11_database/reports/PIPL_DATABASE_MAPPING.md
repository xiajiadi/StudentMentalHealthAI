# PIPL Database Mapping

This is an engineering mapping to the official PIPL text, not legal advice or
a compliance certification. The reference text is the [official CAC
publication](https://www.cac.gov.cn/2021-08/20/c_1631050028355286.htm).

| PIPL principle/article | Database implication | Control in Round 1 | Evidence | Deferred legal/ethics question |
| --- | --- | --- | --- | --- |
| Article 6: clear purpose, direct relevance, minimum scope | Do not create direct identity or unnecessary psychological columns. | Account/Subject split; opaque references; no ERP expansion; field-level dictionary. | `DATA_PRIVACY_MODEL_V1.md`, `DATA_DICTIONARY.md`, schema tests. | Exact purpose and population for a future study. |
| Article 19: shortest necessary retention | Retention must be policy-driven and data-specific. | `retention_due_at`; explicit synthetic purge routines; no fake duration. | `DATA_RETENTION_POLICY_V0_1.md`, lifecycle tests. | Approved duration and exceptions for real data. |
| Article 28: sensitive personal information | Assessment, support, safety, and under-14 information need strict controls. | Fernet encryption for sensitive payloads; queryable metadata separated from content; real-data gate. | `DATA_PRIVACY_MODEL_V1.md`, crypto tests, privacy matrix. | Whether a proposed real field is necessary and what enhanced measures apply. |
| Article 29: separate consent for sensitive information | Consent events must be versioned and historically preserved. | `consent_records` stores policy/document version, scope, grant/withdrawal status; records are append-oriented. | Consent repository and schema constraints. | Consent wording, basis, guardian workflow, and withdrawal effects. |
| Article 31: under-14 information | Do not infer or silently model guardian/legal authority. | No age or guardian legal claim in Round 1; relationship vocabulary only; Backend/ethics gate required. | Technical decision, Backend mapping, no real data. | Population age boundary, parent/guardian proof, and specialized rules. |
| Article 47: deletion | Erasure must remove/anonymize configured data, not only set a timestamp. | Explicit synthetic subject erasure order; payload purge; safe audit tombstone. | Lifecycle service and retention tests. | Real deletion scope, legally required exceptions, and evidence format. |
| Article 51: classification, encryption, de-identification, access control | Data dictionary and field controls must be reviewable. | Six data classes, encrypted binary fields, hashed secrets, least-privilege roles, no raw audit content. | Privacy matrix, OWASP mapping, role evidence. | Production key management, access review cadence, and incident process. |
| Articles 55-56: personal information protection impact assessment | Sensitive/automated processing needs a recorded impact assessment before real use. | Round 1 blocks real data and records this as a prerequisite. | Real-data gate in privacy model and acceptance report. | Formal PIPIA scope, owner, review, and approval record. |

## Boundary notes

- A consent row is a persistence record, not proof of legal sufficiency.
- Fernet, MySQL encryption, hashing, and least privilege reduce risk but do not
  establish legal compliance.
- Database state values such as `REVIEW_REQUIRED` and `CRISIS_ROUTE` are
  workflow values supplied by the Safety/Backend boundary, not legal or
  clinical interpretations made by this module.
