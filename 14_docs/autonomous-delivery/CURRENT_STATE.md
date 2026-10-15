# PsyNova current execution state

Updated2026-10-15 after explicit human Continue. ACTIVE; no new shutdown deadline.
The previous06:30 CST deadline was satisfied before shutdown and was explicitly
revoked by the later human Continue. Do not reapply historical deadlines.
Historical states/receipts remain in Git history (929a341 and earlier) and their
original external artifacts. This file records current facts only.

## Workspace, execution and preservation

- Canonical D:/Projects/StudentMentalHealthAI-m0-integration; dedicated branch
  xiajiadi/autonomous-delivery-20261011. Reviewed code929a3414059ed0e37128dde4e84c62b2af23cb49
  was pushed to origin. Prompt1.4 codef8dc81edc5b385d672cf0cc9bdf94ff5f5f5a6f6
  is also pushed; use actual HEAD for later state increments.
- Goal ACTIVE; heartbeat psynova ACTIVE; Runner stopped=false,
  public_empirical_resources/root/attempt3 lease checkpoint renewed this run.
  These are scheduling/state facts, not unattended execution or final acceptance.
- Root directly delegates Luna/high workers; no Lead/recursive delegation.
  The task-bound held-candidate increment is implemented and under integration
  review. Direct workers own bounded config/runtime/container/deployment/frontend
  work; Root reviews actual changes and native readiness. Prompt1.4 research-only
  constraints remain; native r13 semantic review FAILED as detailed below.
- Preserve user untracked10_frontend/output/ and
  10_frontend/public/assets/heartbridge/login-mark-v2.png. Preserve databases,
  keys, backups, old helpers/failures and all800 existing completed sessions.

## Current running installation and ownership

Q D:/Projects/.StudentMentalHealthAI-school-install-20261015-q,
UUID98ca312250aa6ff6b7f61942d3f78bf6, DB3325/API8099/UI4189/CAT57419,
runtime revision20261015_0019. P source directory remains required for restored
installation lineage: D:/Projects/.StudentMentalHealthAI-school-install-20261014-p,
UUID7d9eeefbb52a00c93e069904e98081b4, DB3324; P remains stopped.

Q official app restart atf8dc81e passed, retaining every research flag and worker:
D:/Dev/temp/psynova-q0019-official-restart-r5-prompt14.json. Backend/Frontend OWNED/READY,
DB VERIFIED. No DB or dependency-host restart. The unexecuted-stop r3 helper
failed because it called instance validators on a module; Root corrected r4 and
reviewed read-only preflight before official stop/start.

Selected student config:
Q/research-config/student-source-r3-20261015/student-lane.json,
SHA048a281d4842fdfd1a00277ae952a5a7d5c5a7d19799c9a836ecd4348026ad54.
Other original research configs remain Q/research-config/q0019-restore-r1/.
Old student config SHA1d0db6209a6bfb392d5e5dc063afec4c458e08db0774a6d2569330f8f7e6ef12
remains unchanged. Old R1-only helper preflights intentionally reject R3; never
revert config or omit flags merely to satisfy an obsolete helper.

Owned dependencies Runtime8160/Ollama11437, Safety8190/OPA8181, RAG8170,
research Runtime8161: original this-run ownership proof
D:/Dev/temp/psynova-dependency-recovery-owned-20261015-070207-f9ddca8f/owner-ready.json.
Only its8191 row is obsolete. Authoritative R3 Safety8191 ownership:
D:/Dev/temp/psynova-research-safety-r3-owner-20261015-090724-375856be/owner-ready.json;
fresh read-only process/listener/health proof
D:/Dev/temp/psynova-research-safety-r3-owner-refreshed-20261015-r3.json.
Listener31256; verify PID/creation/argv afresh before stopping anything.
RAG8170 is synthetic university data; the student research lane uses the separate
real-source package. RTX3060/12288MiB observed. Fixed Ollama0.33.3,
qwen2.5:7b-instruct-q4_K_M / logical qwen2.5-7b-instruct-school-demo,
digest845dbda0ea48ed749caafd9e6037047aa19acfcfd82e704d7ca97d631a0b697e;
contract MODEL_local_primary, runtime0.1.0-school-demo, no cloud fallback.

## Real RAG sources and current content-quality blocker

Active manifest:
D:/Dev/datasets/psynova-public-research/staging/student-general-education-source-review-20261015-r3/manifest.json,
SHAac9cc1641faa565ff7a18866be1c2dbf8aaf16aff7155ea80c38bfd979429a9b.
WHO HAT/physical activity, Raniti connectedness review, Gaskin sleep review;
Firecrawl/direct official acquisition, rights records and exact text hashes.
Four eligible excerpts, three layers; CDC trace-only. Consumer14-17 intersection;
original populations/languages retained, research-only/all approval flagsfalse.
R1 and R3 are closed hash-pinned supported versions; R1 default unchanged.

8c97097/prompt1.3 fixed a genuine missing-text defect: Runtime previously got only
citation IDs/locators. Research now sends exact bounded untrusted source text;
47 focused service tests passed. Existing guards/university mode unchanged.

R3 once r9 failed before Runtime: full locator+population+URL+license/URL+
attribution exceeded512 chars for all4 sources. Actual GET-only recovery:
CONV_f35b2223ecde4def8b133e4823092325 / TURN_a0596139490f42b490379a345255ba4b,
failed/DEPENDENCY_FAILURE, stage=retrieval/dependency_invalid_response.
D:/Dev/temp/psynova-q0019-student-research-api-once-r9.json preserves helper FAIL;
original POST was not replayed. r10/r11 assumed prompt version existed despite
pre-generation failure; their assertion failure is not a model failure.

929a341 fixes citation projection: keep legacy format when it fits; otherwise
stable record reference plus every population/URL/license/attribution field
verbatim. Full record locator remains location.section and the pinned package.
No schema widening, metadata truncation or organization-field repurpose; remaining
overflow still fails closed. Root5 tests passed; actual R3 converter verified
4 hashes/3 layers and locator lengths358/446/378/411.

NEW r12 completed once after restart, native fixed7B/3 R3 citations/Safety/claim/
citation checks. Evidence D:/Dev/temp/psynova-q0019-student-research-api-once-r12.json.
CONV_d48d19ebac0a48c38c77e16287cbee48 / TURN_0eaedf1aa9f543e28ec22d5fccfe4a2d,
content SHA2ea788137c971f53b17114ddac7b4af13624c8dc4496aca9bcd49d8507a37e14.
Root GET-only readback matched body/hash/source hashes and logouttrue.
CONTENT REVIEW FAILED: it applies limited sleep-intervention findings to physical
activity and invents a combined sleep-education/exercise proposal. Preserve this
exact answer; transport/provenance completion is not semantic acceptance.
Prompt1.4/f8dc81e adds generic source-by-source constraints, negative-result/
population separation and insufficient-evidence behavior.47 focused tests passed;
university prompt unchanged. After official restart, NEW r13 once completed with
valid3 citations, pinned Runtime and single attempt; same-turn GET/hash/logout
verified. CONV_47fb43eef67146d29b36b4b0c6e131d7 /
TURN_72cad08c0af04a9eac88a621ae13478c,
content SHA9b0cbe9489b7ef723e1ce3e82d25bb0f8e0bf3a5ecbcc9a05e167f38e12365c7.
Root content review again FAIL: WHO weekly-average qualifier lost; Gaskin
single-study/high-bias/one-week limits lost and converted to a school action.
D:/Dev/temp/psynova-q0019-student-research-api-once-r13.json and
psynova-q0019-r13-root-content-review.json preserve separate outcomes.
Stop prompt-only model loops. Next: inspect reuse of existing encrypted candidate/
review/explicit-release workflows, retaining source-specific evidence limits;
Root must decide a bounded implementation before any new model attempt. Audit
confirmed programme candidates are task-bound/STAFF_REFERENCE_ONLY and feedback
records require completed research CAT sessions; neither can silently become an
independent-conversation release path. Existing blocked/failed turns cannot hold
approved content. A separate research candidate/release design must preserve
conversation privacy, explicit student sharing consent, assigned specialist
scope, encrypted payload/citations and separate approval/publication. Do not
repurpose crisis/safety cases as ordinary evidence-review cases or grant general
specialists access to private chats. University mode and frozen contracts remain
unchanged. No source-specific hardcoded answer, guard loosening, JSON repair or
blind retries. Next first step is a small explicit design and bounded ownership
before any additive schema/API work, not another prompt-only generation.
Earlier failed/partial r1/r2 sources and turns remain unchanged; see Git history.

##800 cohort, staff queue and completed workflows

COHORT_R_b35676ba82d7455eaf58a2b4f8090826,
SYNTHETIC_SCHOOL_SEED_ALPHA_V1, HUNNU_PROMIS_HISTORICAL_REPLAY_2026_R1:
800cases/8classes/800subjects/8tasks/800completed PUBLIC_OBSERVED sessions,
SUM(items_answered)=6400. Do not rerun/reseed. This study differs from RAG study
school-noncommercial-rag-research-2027-06; preserve task-level specialist scope.

2 staff reference jobs HELD,798 without staff-policy job. They are literature
catalogue candidates, not student reports. Batch2 exact-key replay/no extra job
and real UI/GET pagination/counts verified; teacher/admin/student GET403.
Evidence D:/Dev/temp/psynova-q0019-staff-batch-native-r4.json,
psynova-q0019-generation-jobs-get-r2.json,
psynova-q0019-student-research-staff-ui-once-r9.json. Root viewed UI screenshot;
queue-only browser guard blocked2 unrelated GETs; no whole-overview acceptance.
Completion-trigger education lane lacks approved processor and abstains with
POLICY_UNAVAILABLE; do not claim800 AI feedback completed.

Prior native/browser evidence preserves four-role provisioning, completion,
review/draft/explicit publish/student read/revoke and denied Scope A access.
Safety case SCS_01a69ae5cc0c3a3235dc52a05e4a6ff12d79f2a00064b678 is
ESCALATION_NEEDED v8 with encrypted note and8 events; no closure/contact/approval.
Actual Q DB restart and authenticated encrypted readback passed earlier.
P-to-Q restore matched55 business tables34023rows/865 ciphertexts. Pre-resume sealed
Q backup20261014-221528-d2a6ca2893d04ca6842e92d7df1e8c8a.private.dpapi,
SHA0e3569c29e9948c743452701ae5f8eb5267821122f47742876b8e5bc046f8266,
58tables34282rows includes v8 but predates this run's new jobs/turns/auth rows.
NEW Q sealed backup and readback verified58tables:
Q/backups/20261015-100726-1654b0b61d9a4c3bb105f655ff1db5ba.private.dpapi,
SHA838965e47b7f35eeef26d3dc7e6c5cbb3f825ebe4a8317fa8b01a1f14d5cfe0b.
Revision0019; current-Windows-user DPAPI/new-isolated-instance restore only.
This is sealed snapshot evidence, not a new restore acceptance. Keep old backups.

## Installation and remaining delivery work

Fresh offline dependency installation completed at identical5dfa0e3 source/target:
D:/Dev/projects/smhai-offline-deps-20261015-5dfa0e3-r1. All8 official stages passed
(six Python versions/imports, frontend locked packages, manifest integrity),
exit0/state persistence succeeded. Root inspected report and tracked diffs.
D:/Dev/temp/psynova-offline-install-20261015-r1.json,
SHAf7278efe7db8153beb5ecba9fad07317729138341f4a2f2157544e96676d4ad2.
Target/state/npm files preserved. This proves this host's cached dependency prep;
portable model/OPA/Guard/vector assets and fresh-install service startup remain
separate. No cleanup/retry of any failed target.

## Active increment: exact-session held candidates (2026-10-15)

Planning estimate supplied to operator: engineering about75percent complete,
25percent remaining. This is a scope estimate, not acceptance or production approval.
Direction is RESEARCH_GENERAL_EDUCATION_CANDIDATES.md: reuse completed800 sessions,
new RESEARCH_GENERAL_EDUCATION_DRAFT_V1 policy, immutable encrypted0020 candidates,
assigned specialist source review, separate edited feedback draft v2 with lineage,
existing case APPROVED gate and explicit publish/student SELF read/revoke.
Private chats and0018 staff reference catalogue remain independent.

Implemented: database migration/repository/UOW/restore registration; exact-session
candidate API and bounded enqueue; one-attempt worker and shared-lock manager;
fixed person-free Runtime8161 route; R3/all-three-Safety processor; opt-in config,
container/lifecycle and feedback v2 integration. Source excerpts/population/license
and original generated payload are retained. No assessment answers/scores/snapshot
are passed to the new processor. Every successful generation stays HELD.

Root fresh targeted checks:116 backend processor/runtime/candidate/feedback/worker/
settings tests,24 manager/container/previous-worker tests,41 database candidate/
outbox/feedback/schema tests passed. Independent review then fixed MySQL constraint
identifier lengths and nullable lineage CHECK bypass;42 adjacent database tests
passed after that fix. Frontend source display/candidate review/link-to-draft is
implemented; typecheck/targeted ESLint and28 existing feedback/programme checks
passed. Identity changes clear private UI state; old manual-feedback DTOs remain
compatible. These checks do not establish actual browser or native inference proof.

Native0020 migration/restore, new route inference and browser review/release have
NOT run. Q remains0019/f8dc81e with all existing800 sessions preserved. Do not
restart Q using CURRENT0020 code. Next use a fresh isolated forward restore from
the sealed Q backup, verify source/config/owned dependencies, then ONE native
candidate and its complete review/draft/publish/read/revoke browser journey.
Only after that acceptance enqueue remaining bounded800 work; no blind model reruns.

Priority: finish held/review/release integration, source-grounded content review,
useful empirical AI workload and installation/recovery acceptance.
Retain Contract/D4/HumanGold, licensed public-data population provenance and
privacy. PROMIS school noncommercial declaration is not proprietary CAT/app
permission. No psychometric/clinical/ethics/school-production approval, protected
branch merge/tag/release or actual school deployment is granted by engineering.
