# NHANES complete-response engineering coverage scenario

Date: 2026-10-14. Status: `RESEARCH_ONLY / CONTROLLER_REVIEW_REQUESTED`.

## Purpose and source

This separate response-only artifact prepares 800 complete ordinal response vectors for an engineering workflow using fictional accounts. It is an additional coverage scenario; the existing 6,000 calibration rows, original 800 evaluation rows, and fitted mirt parameters remain unchanged. The new sample excludes every reconstructed calibration record and every original evaluation record.

Source: NHANES 2017–March 2020 pre-pandemic public-use adult P_DPQ response-only CSV, SHA-256 `1a050397dc420e8eb685a43a5a7b481bb3ff61c38e3b5f4d6fb00988a15a2091`; upstream source manifest SHA-256 `73827fd3be8a353ae6ecf97ff52982cfe57a96da220d0b33878361e80f7ceec5`. The nine columns are `DPQ010, DPQ020, DPQ030, DPQ040, DPQ050, DPQ060, DPQ070, DPQ080, DPQ090`. The source extract retains distinct 7 (refused), 9 (don't know) and blanks. Eligibility for this separate complete-record cohort requires every cell to be 0–3; no missing value was filled or converted into an observed answer.

## Reconstructed frame and selection

The existing importer `901d09e23f95c58ebd5f3d5cb2676822df25f1a2c6b89fe4634c592fa4ea99e2` was invoked in memory with seed `20261014`, calibration size 6,000 and evaluation size 800. The rebuilt calibration/evaluation response bytes reproduced the original split hashes exactly. Temporary source row markers were used only in memory for exclusion and disjointness checks and were not persisted.

- Source rows: 8965; complete on all nine items: 8276.
- Complete candidates after excluding all calibration rows: 2747.
- Complete candidate pool after also protecting all original evaluation rows: 2002.
- Selected: 800, without replacement, fixed seed `2026101402`. All 800 are unique and have zero overlap with either the calibration or original evaluation set.
- Selection uses Python `3.14.6` standard-library `random.Random(seed).sample` over source-order complete candidates. The exact transformed response CSV SHA-256 is `5dbbd84a4841f43ae090135ebd225b8e1d84ff3089326410d8bc4012a03cbc6d`.

Output remains outside Git at `D:\Dev\datasets\psynova-public-research\derived\nhanes-dpq-engineering-coverage-800-20261014-v1\`; it contains only nine allowlisted numeric response columns and an aggregate manifest. No participant or source identifiers, row positions, demographics, text, per-person theta, scores, or labels are stored.

## Limits

This complete-case sample is intentionally selected for engineering coverage, not as an unbiased estimate or a replacement held-out set. Complete-case filtering may introduce selection bias. NHANES P_DPQ here is an adult public-use source without demographic fields in the extract; it does not establish adolescent, high-school, school, or individual measurement validity. DPQ090 remains an ordinal answer and is not a current crisis label. No model was refit, no parameter or bank was changed, and this isolated artifact is not approved for product/database admission, publication, or redistribution.

Original baseline directory: `D:\Dev\datasets\psynova-public-research\derived\nhanes-dpq-20261014-v1\`. Original calibration, evaluation, manifest, and fit artifacts were hash-checked after generating this scenario.
