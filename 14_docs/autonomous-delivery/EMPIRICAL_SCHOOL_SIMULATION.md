# Empirical school simulation acceptance

Operator extension: 2026-10-13. This is required engineering acceptance work,
not an approval of psychometric validity or school production deployment.

## Scenario and source identity

One fictitious school, one grade, 800 fictitious students distributed across
classes. School names, names, student numbers and login identities are generated
simulation identities; no public research participant becomes a school identity.
Real published items, scoring keys, response matrices and calibrated parameters
retain their source population, language, license, missing-value conventions,
version and transformation record. Adult personality data may test the engine,
but cannot establish high-school mental-health measurement applicability.

Prefer an age-appropriate, established adaptive item bank with published item
parameters and compatible responses. Do not manufacture calibration parameters
or clinical labels. If fitting research parameters from public responses is
necessary, split calibration and evaluation participants, preserve reverse-key
and ordinal coding, report fit/misfit, uncertainty and assumptions, and label the
parameters research estimates. Never overwrite frozen Demo or accepted evidence.

## Required complete workflow

1. Specialist imports a source-traceable item bank; validates schema, item text,
   dimensions, response categories, parameter version and provenance. Administrator
   imports 800 fictitious roster entries and provisions 800 distinct accounts.
2. All 800 accounts authenticate and receive the intended class/task scope.
   Each has an independent CAT session driven by a deterministic mapping to an
   eligible public response profile. Preserve real missing responses; explicitly
   report exclusions and stop reasons instead of silently inventing answers.
3. Exercise save/resume, duplicate submissions, expiry, failure/recovery and
   completion. Reconcile 800-account/task/session counts with database facts.
   Compare adaptive estimates against an independently computed full-bank baseline
   on held-out data; report error, test length, exposure and failures.

   Public-observed replay provenance must be enforced by the server: pin the
   response matrix and deterministic enrollment-to-case assignment, and validate
   each submitted raw value against the assigned observation. A client-selected
   value or an operator-created example cannot acquire PUBLIC_OBSERVED provenance
   merely because its task uses a public item bank. Keep manual synthetic examples
   separate. Case mappings stay private; publish aggregate coverage, source hashes
   and exclusions without research-participant identities or per-person hashes.
4. Post-completion background education-support processing uses a durable queue,
   bounded concurrency, idempotency and restart recovery. RTX 3060 capacity is
   measured; 800 total users does not imply 800 simultaneous model generations.
   No answer is silently replaced by a fixture or cloud fallback.
5. RAG uses real primary-source material in the existing policy/theory/intervention
   layers, with source permission, population applicability and review state
   preserved. Every generated citation resolves to the retrieved source/version.
   Missing evidence produces abstention. Public source status does not itself
   constitute human professional review or production publication authorization.
6. Keep L1 completion, professional-approved L2 eligibility, and L3 manual review
   distinct. Generated content stays within educational support; prohibited claims
   and unsafe outputs are withheld and routed to review. Test assignment, review,
   publication/retraction, authorization and encrypted persistence.
7. Dangerous input and output scenarios exercise the crisis circuit breaker,
   interruption of ordinary generation and human-review routing. Do not treat
   public questionnaire item scores as ground-truth suicide labels or use them
   to invent thresholds. Explicit deterministic safety cases supplement empirical
   response replay and are reported as separate injected test cases.
8. Verify teacher completion-only views, administrator operations-only access,
   specialist task-scoped access and cross-school/student denials through Backend.
   Verify install, backup, restore, shutdown and restart with the same counts and
   outstanding jobs. Capture real browser evidence for every role and boundary.

## Evidence and completion

Maintain a concise source manifest and aggregate-only results outside sensitive
data. Acquisition tools and major sources are summarized briefly for the operator.
Raw/public research rows, credentials and per-person psychological outputs are
not committed or printed. Derived response-only research data stays on D: outside
the school Demo database and Git.

Acceptance requires reconciled counts, reproducible seeds/versions, independent
QA, actual browser/API/database observations, explicit failures and measured
performance. Do not claim 100 percent fidelity, zero real-world risk, clinical
validity or production readiness solely from a successful simulated run.

Next increment: acquire the first correctly keyed public item/response resource;
build a response-only validated importer and held-out CAT replay; qualify an
adolescent bank separately; then run the 800-account workflow in a new isolated
scenario workspace with source-specific evidence.


## Cohort-wide observed replay assignment (Controller direction, 2026-10-14)

Task-level case uniqueness is insufficient for the8-class/800-student mandate.
Introduce an explicitly server-owned research cohort with pinned school/study/profile/
manifest/corpus identity, selected existing import batches and an immutable sealed
membership snapshot. Seal verifies actual synthetic subjects, unique current SELF
relations and roster/batch provenance in one transaction. The800-person acceptance
cohort must own800 distinct subjects and a complete one-to-one0..799 case mapping;
never infer this from a file's scenario_id or client assertions.

The cohort's private subject/case mapping persists independently of each task.
Task publication joins existing sealed members and copies/references their mapping,
rather than sampling again for each class. Repeated tasks for the same subject refer
to the same case. Revocation stops future use but does not recycle/reassign the case;
new members require a new cohort. Legacy task mappings are not retroactively stamped
as cohort-verified. Assignment indices/source rows stay out of public DTOs/logs/UI.

Enforce cross-school isolation, immutable study pins and stable lock order. Seal and
publish are atomic; uniqueness/FK constraints enforce subject/case correspondence.
Report separate counts for unique assigned, started, answered and completed source
cases from persisted server data;800 actions/allocations alone do not prove800
observed completed cases. Professional/ethics/clinical approvals remain false.
This is the next additive engineering increment after native0014 verification;
no cohort schema, API or online800 execution has yet been implemented or accepted.
