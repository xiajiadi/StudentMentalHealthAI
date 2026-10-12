# University learning support knowledge intake

**Status:** `pending_review` — candidate-source research only; nothing here is an approval, rights verification, human-curated source, or publication decision.

**Research checked:** 2026-10-12 11:18 UTC
**Purpose:** Find narrowly scoped, openly licensed university learning/time-planning material that could address the independent RAG population gap. No source asset was downloaded or copied into the workspace, run through the pipeline, or added to a corpus in this task.

## Why ordinary university queries currently abstain

The current project state records that the real published corpus has 14 K-12 chunks and zero university matches for both independent populations. The independent RAG path accepts only exact `university_freshman` or `university_student` scope and filters for `review_status=approved` and `rights_status=verified`; it does not relabel the K-12 records. See [`CURRENT_STATE.md`](CURRENT_STATE.md), [`independent.py`](../../05_rag-engine/src/rag_engine/independent.py), and [`corpus.py`](../../05_rag-engine/src/rag_engine/indexing/corpus.py).

The Knowledge Pipeline already has the needed lifecycle: only an approved review decision, verified rights, and passing or warning quality status can publish a chunk. `pipeline.v1.yaml` keeps `publish_only_approved: true` and `allow_test_auto_approve: false`. The task explicitly excludes pending, rejected, or restricted records from production retrieval. See [`TASK.md`](../../04_knowledge-pipeline/TASK.md), [`pipeline.v1.yaml`](../../04_knowledge-pipeline/config/pipeline.v1.yaml), and [`ReviewGate`](../../04_knowledge-pipeline/src/knowledge_pipeline/review/gate.py). Therefore, source discovery alone cannot change retrieval eligibility.

## Candidate sources

Both candidates below are official Kwantlen Polytechnic University (KPU) Pressbooks materials with explicit CC BY-SA 4.0 statements. This is evidence of an open license statement, not a determination that this particular project’s storage, derived summaries, AI retrieval, or distribution satisfies every applicable term. Keep each item `pending_review`; do not set `rights_status=verified`, `review_status=approved`, or `human_curated=true` from this intake.

| Candidate | Official source, publisher, and scope | License evidence and reuse obligations | Narrow content to review | Limits / review questions |
|---|---|---|---|---|
| **Time Management for Busy Students** | [Book page](https://kpu.pressbooks.pub/timemanagement/) and [“Schedule Your Semester”](https://kpu.pressbooks.pub/timemanagement/chapter/scheduling-your-semester/), [“Manage Daily Tasks”](https://kpu.pressbooks.pub/timemanagement/chapter/managing-daily-tasks/). KPU Learning Centres; Kwantlen Polytechnic University; copyright/publication 2018 (book metadata gives May 31, 2018). Intended for students managing university study alongside other commitments; one pathway is explicitly for new KPU students. | Book and chapter pages state [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/), except where otherwise noted. The license permits sharing/adaptation subject to attribution, license link, change notice, and ShareAlike for distributed adaptations. Attribution should name KPU Learning Centres/Kwantlen Polytechnic University, title, and source. The book page also specifies the attribution phrase “Download this book for free from the B.C. Open Textbook Collection.” Review whether that notice applies to the planned use and what exact attribution must accompany retrieved or adapted material. | Review only the semester overview and daily-task planning sections first. Possible Chinese summary scope: use course outlines and deadlines to make a semester view; break a large assignment into manageable tasks; choose and prioritize a daily task list that fits current commitments. Do not import worksheets, videos, screenshots, images, or institution-specific links in this first pass. | This is a 2018 KPU workshop, not a universal rule set. Review transferability to non-KPU students, any embedded examples or third-party material, the ShareAlike implications for a localized synopsis and retrieval use, and whether the unit is educationally appropriate for the intended university population. Do not turn its scheduling examples into guaranteed grade outcomes or fixed study/rest prescriptions. |
| **University 101: Study, Strategize and Succeed** | [Official book page](https://kpu.pressbooks.pub/studystrategizesucceed/) and relevant [chapter “Create a Weekly Schedule that Works”](https://kpu.pressbooks.pub/studystrategizesucceed/chapter/create-a-weekly-schedule-that-works/). KPU Pressbooks says the book supports undergraduate and adult-education learners, including new, returning, mature, international, and continuing students. Chapter 12 is part of “Manage Your Time: Study Strategies for Busy Students.” | The book/chapter state [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/), except where otherwise noted. Preserve attribution, license link and modification notice; ShareAlike applies to distributed adaptations. The book-level page credits KPU Learning Centres and editor Christina Page, while the chapter license footer says copyright © 2018 by Megan Robertson. Use both source and chapter-level credits in the candidate record until a human reviewer confirms the right attribution format. | Review the chapter’s method of placing class/lab times, travel, meals, work and recurring activities into a weekly plan; leaving open time; checking the plan after trying it. Possible Chinese summary scope: help a student build and adjust a schedule from their own commitments, without promising an ideal timetable. | The chapter includes specific “30 minutes before/after class” suggestions and a sample timetable. A reviewer should decide whether those should be presented only as examples from this chapter or omitted from a concise summary. Do not encode those values as universal rules or as rest-interval guidance. Exclude the chapter’s forms and images unless their individual rights are separately checked. Confirm chapter-specific attribution noted above. |

### Not a ready-to-ingest candidate: OpenStax College Success Concise

OpenStax’s current [Preface / reuse page](https://openstax.org/books/college-success-concise/pages/preface) describes CC BY-NC-SA 4.0 and explicitly says the book may not be ingested into LLMs or generative-AI offerings without prior written permission. It also calls for attribution and ShareAlike for redistributed derivatives. An OpenStax-hosted 2023 PDF surfaced in search with a different CC BY 4.0 notice. Because the current official web page has an AI-ingestion restriction and the accessible license notices conflict, do **not** add this title as a candidate source or to the corpus until the rights owner resolves the version/license discrepancy and grants any required written permission. This is a rights-source conflict, not an invitation to select the more permissive notice.

## Suggested Chinese synopsis boundaries

If a human content reviewer selects one of the KPU candidates, keep the first synopsis limited to general education about:

- making a semester/weekly view from the learner’s own course deadlines and recurring commitments;
- dividing a large assignment into smaller, concrete next actions;
- prioritizing daily tasks and revising a plan when it does not fit;
- asking instructors or campus learning-support staff about course-specific expectations when the learner needs local guidance.

Exclude psychological interpretation, diagnosis, test-score claims, treatment or crisis guidance, and claims that a schedule guarantees grades. This source set does not support a universal answer for “study X minutes, then rest Y minutes”; neither introduce fixed intervals nor imply the KPU chapter’s examples answer that question. The summary should cite the exact chapter used, distinguish source-derived guidance from any local adaptation, and be reviewed before it is marked human-curated.

## Minimum next pipeline action

Before source rights are settled, engineering may prepare a separate staging-output path and a synthetic-only gate check that confirms `pending_review` or unknown rights cannot enter publication and that population filters stay exact. Such a placeholder is only a gate fixture; it must not be presented as educational evidence or added to the live retrieval corpus.

1. A rights/content reviewer selects one chapter and records exact canonical URL, page title, author/organization, publication or copyright date, access timestamp, license URL, any attribution text, page-specific exceptions, intended population, and whether local RAG/AI retrieval and the planned distribution are permitted. Keep rights unknown until that review is actually complete.
2. After that review, preserve a single official source page as an immutable raw input with source URL and content hash. Do not bulk-download a full textbook. First run it through the existing raw HTML/document path with review still pending; inspect the canonical output, source location, quality report, and review queue. Do not mark it curated just because its publisher is a university.
3. A human education-content reviewer may then author a short Chinese synopsis with attribution and a source locator. Only that person may set curated metadata and make a separate review decision; rights verification remains a distinct decision. Test the exact population mapping (`university_student` versus `university_freshman`) rather than broadening filters or relabeling K-12 material.
4. Publish only after both the content review and rights decision are recorded and the quality gate passes. Then rebuild a separate approved publication and its BM25 index, and verify the specific university query returns eligible cited evidence while the K-12 corpus and existing frozen publication remain unchanged.

No existing corpus or index has been changed by this intake. Any future publication should be additive and separately versioned; do not overwrite or edit the current frozen publication as part of source discovery.

## Human decisions still required

- Whether local storage, translation/synopsis, indexing, retrieval, and the intended school deployment satisfy each source’s CC BY-SA conditions.
- Exact attribution and ShareAlike handling, including how attribution/changes appear in stored metadata and generated citations.
- Whether each chapter is accurate and appropriately scoped for `university_student`, `university_freshman`, or both; these are not interchangeable labels.
- Which specific recommendations (especially fixed 30-minute examples) should appear in user-facing educational support.
- Whether to exclude third-party figures, videos, worksheets, surveys, or embedded links from the initial source package.

These are source-rights and educational-content review decisions. This document records candidates and a safe engineering sequence; it does not make those decisions or authorize publication.
