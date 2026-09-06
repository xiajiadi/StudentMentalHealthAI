# Data Privacy Model V1

Status: ENGINEERING DESIGN BASELINE  
Scope: Database Round 1  
Data posture: synthetic fixtures only  
Legal status: not a legal, ethics, or PIPL compliance certification

This model applies data minimization and purpose limitation to the persistence
boundary. It separates authentication identity from the pseudonymous subject
being assessed or supported. Database controls reduce exposure; they do not
replace authorization, informed consent, privacy impact assessment, or a
review by the project owner and qualified privacy/ethics professionals.

## Data classes

| Class | Examples in this module | Storage rule |
| --- | --- | --- |
| PUBLIC / NON-SENSITIVE SYSTEM | schema version, role vocabulary, migration revision, component version references | Relational or bounded JSON; no user content. |
| INTERNAL | trace IDs, workflow status, rank, timestamps, safe reason codes, resource references | Queryable relational fields; do not place content in metadata. |
| PERSONAL | account login name, pseudonymous subject reference, access relationship, consent event metadata | Minimize; use opaque IDs; restrict access; retain only as policy requires. |
| SENSITIVE_PERSONAL | authentication/session hashes, consent and access history, under-14 status if ever introduced, health-related workflow metadata | Hash or encrypt where appropriate; do not add direct identifiers in Round 1. |
| PSYCHOLOGICAL_SENSITIVE | assessment answers/results, user support text, approved delivered support text, safety details, review notes | Application-level Fernet encryption; no plaintext search or ordinary logs. |
| SECURITY_SECRET | passwords before hashing, raw session/CSRF tokens, encryption keys, DB passwords | Never persist raw values in this module; keys and credentials stay outside the repository/database. |

Classification is field-level, not table-wide. For example, review queue
status and priority are queryable INTERNAL fields while a review note is
PSYCHOLOGICAL_SENSITIVE and encrypted.

## Storage and queryability

- Internal primary keys are not exposed as authorization identifiers. Resource
  rows also have UUID4 `public_id` values; the Backend remains responsible for
  authorization and scope checks.
- `subject_ref`, `assessment_ref`, `support_ref`, `run_ref`, `decision_ref`,
  and `review_ref` are opaque integration references. They are not names,
  student numbers, phone numbers, or contact details.
- Operational state, priority, assignment, timestamps, trace IDs, and citation
  references remain relational so a queue or audit view can work without
  decrypting content.
- Encrypted JSON is deterministic before encryption and carries a payload
  schema version in a separate column. It is not pickle and is not searchable.
- No full-text index covers psychological messages, answers, results, safety
  detail, or review notes.
- `safe_metadata` and `component_versions` are bounded JSON objects controlled
  by an allowlist. Arbitrary request or ORM serialization is not allowed.

## Encryption and key handling

- `FernetDataProtectionProvider` uses pyca/cryptography. Fernet provides
  authenticated encryption; custom AES, MAC, padding, nonce, or token formats
  are not implemented here.
- Each encrypted field records `cipher_format_version`, `key_version`, and
  `payload_schema_version`. It never records key material.
- `DevLocalKeyProvider` reads a JSON key file outside the repository. The
  default example path is `D:\Dev\secrets\studentmentalhealthai\database-keys.json`;
  operators should configure an equivalent protected location.
- Test keys are generated in the test process and are never the development or
  production key.
- A `MappingKeyProvider` plus `rotate()` proves the Round 1 rotation path:
  old v1 ciphertext decrypts, v2 becomes active, the record is re-encrypted,
  and old-key-only decryption fails.
- Missing or wrong keys fail explicitly. Ciphertext is never returned as
  plaintext and empty values are not substituted.
- MySQL/Tablespace/redo/binlog at-rest encryption is defense-in-depth. It is
  not enabled as a Round 1 hard gate and is not presented as legal compliance.

## Retention and deletion

- `retention_due_at` is a policy reference, not a hardcoded legal duration.
- `DATA_RETENTION_POLICY_V0_1.md` describes only synthetic engineering
  behavior. A real-data retention schedule requires owner, ethics, and legal
  review.
- Business states such as CLOSED, REVOKED, ARCHIVED, or ERASED are not the same
  as personal-data erasure.
- `SyntheticLifecycleService.erase_subject()` has an explicit dependency
  order, removes configured synthetic child records, clears the subject's
  opaque reference, marks the subject ERASED, and records only a safe audit
  tombstone.
- `purge_due_encrypted_payloads()` removes due synthetic ciphertext and key
  metadata. It is not a claim that a legal retention clock has been selected.
- Raw psychological content is not copied into the audit tombstone. Raw RAG
  chunks and unsafe rejected model candidates are never stored by this layer.

## Audit restrictions

Audit fields are actor, action, resource type/reference, result, trace, safe
metadata, and timestamp. The safe metadata allowlist is intentionally small:
`schema_version`, `component_version`, `reason_code`, `count`, `source`, and
`state`. It excludes raw chat, answers, results, passwords, tokens, keys,
review notes, and complete safety payloads.

## Backup sensitivity

Round 1 fixtures contain no real student data, but the logical backup still
contains encrypted psychological payloads and operational metadata. Backup
files remain sensitive engineering artifacts and are written outside the
repository by `scripts/backup_round1.ps1`. Future real-data backups must use
approved encryption, access control, retention, restore testing, and audit
procedures. Round 1 does not claim those production controls are enabled.

## Real-data gate

Real student, assessment, consultation, parent, teacher, psychological, or
health data are prohibited in Round 1. Before any real-data change, the project
must obtain documented purpose/scope approval, consent design, access roles,
retention/deletion approval, privacy impact assessment, key-management plan,
backup plan, and a reviewed deployment boundary. A synthetic fixture is not
evidence of educational or clinical effectiveness.
