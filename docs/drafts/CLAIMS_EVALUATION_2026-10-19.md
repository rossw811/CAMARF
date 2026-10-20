# Claims evaluation, all papers and docs (2026-10-19)

Ross, 2026-10-19: "for all of our claims we need to double check and evaluate if they're worth reporting ... every
claim, that extends to all papers and docs."

## Method
1. **Inventory** (`claims_inventory_2026-10-19.csv`): every reader-facing claim in 12 files -- PAPER.md 270,
   PAPER_MAGNITUDE.md 146, FINDINGS 146, README 49, CONTRIBUTING 41, ERRATA 37, CLAIMS_REGISTRY 27,
   PAPER_PENDING_CHANGES 26, PREREGISTRATION 24, DATA_SOURCES_SURVEY 19, PIT_INDEX_MEMBERSHIP_SOURCES 11,
   PAPER_PROCESS_OUTLINE 10 = **806**. Extracted read-only by a Sonnet agent; Development.md, HANDOFF, BUG_LOG and
   archives are internal logs and excluded.
2. **First pass** (`scripts/triage_claims_inventory.py`): dependency tags (which fix or pending run each claim hangs
   on) and a check route (re-derive / verify against code / data / primary source / confirm withdrawn). Keyword tags
   only route the work; every verdict was made by hand.
3. **Verdict per claim** (`claims_evaluation_2026-10-19.csv`, columns verdict / verdict_reason / evidence):

| Verdict | Meaning |
|---|---|
| KEEP | checked and holds (code, data, re-derived number, record); worth keeping where it is |
| QUALIFY | holds only with a stated scope/caveat, or a dated number to refresh |
| CORRECT | wrong or stale as written; the reason gives the correct statement |
| WITHDRAW | false, or the doc already withdrew it and the withdrawal stands |
| CUT | true (or unverifiable history) but not worth reporting -- old small-set arms, engineering detail |
| PENDING_CHAIN | central; must be re-derived on the 2026-10-19 chain (new pools, PIT spread fix, strict engine) |

"Worth reporting" = holds after the 2026-10-17..19 fixes, central to a paper's argument or a disclosure the reader
needs, and robust (survives the sensitivity it was given). Old small-set comparison arms are cut unless re-run.

## Result (760 of 806 judged; 46 literature claims with the primary-source check)

| | KEEP | QUALIFY | CORRECT | WITHDRAW | CUT | PENDING_CHAIN |
|---|---|---|---|---|---|---|
| all files | 183 | 56 | 31 | 220 | 120 | 150 |

220 WITHDRAW = 217 the docs already withdrew + 3 new (PAPER-012, PAPER-059, README-012).
**90 doc edits** follow (31 CORRECT, 56 QUALIFY, 3 new WITHDRAW): PAPER.md 40, README 11, CONTRIBUTING 10, PAPER_MAGNITUDE
9, ERRATA 5, CLAIMS_REGISTRY 4, PROCESS_OUTLINE 3, FINDINGS 3, DATA_SOURCES 2, PENDING_CHANGES 2, PREREGISTRATION 1.

## What changed, by cause
- **D11 reverses a paper result.** "EG false-positive rate under the null is elevated (7.75-12.75%)" (PAPER-013,
  PAPER-063, README-013) -> the production two-direction screen on calendar-aligned full-universe random pairs rejects
  1.50% (15m), 1.75% (1h), 3.00% (1D), 3.25% (1M) vs 5%. Scope: random pairs; the |corr| >= 0.6 candidate population is
  not measured yet.
- **D13 qualifies the headline illustration.** NTRS/STT: full p 0.0000 (10,097 d) vs last-5y p 0.599 (not 0.561);
  the 5-year test has power 0.18 (Gaussian) / 0.34 (real blocks) at the full-sample effect -- weak evidence either
  way. "Negative controls show the pattern on neither window" is false (XOM/CVX 0.0415/0.3769) -> PAPER-012, PAPER-059
  WITHDRAW; README-012 WITHDRAW (SHW/UNP full p 0.0606 on CRSP, not < 0.005).
- **Today's code fixes make "open" items closed:** A2/A3 full-sample hedge fallback and A4 full-sample z-window
  (ERRATA-022, ERRATA-029, PREREG-015) are fixed (89ececc4); transfer entropy is NaN under strict (PAPER-248).
- **Plain errors found:** entry threshold is |z| >= 3.0 not 2.0 (PAPER-109); the trig invariant is the SUM, not the
  difference (PAPER-203, contradicting FINDINGS-034); seven GapFlag codes, not six (README-039); FX conversion uses
  Compustat g_exrt_dly, not frb_all.fx_daily, and R1.1 is fixed (DATASRC-006); squeeze/momentum gates exist
  (PAPER-220); sensitivity.py no longer drops zero days (FINDINGS-015); 62 broad excepts -> 100 in six modules
  (OUTLINE-009).
- **Stale AI-use disclosure (PAPER.md s9):** "web search used exactly once" (PAPER-245), "Development.md >10,000
  lines" (29,365; PAPER-243), model/session list (PAPER-237), data-source list omits WRDS (PAPER-246).
- **Stale counts:** unjustified parameters 339 -> 291 (README-018, PM-008, PAPER-006); verify scripts ~340 -> 402
  (README-003, CONTRIB-026/037); review-findings status (ERRATA-034).
- **Found in my own work while checking:** the D13 script skipped the S35 no-trade mask (fixed; its numbers now match
  the registry's current_rules re-derivation).

## Worth reporting (after the chain, if they hold)
Central claims to re-derive (150, PENDING_CHAIN): PIT vs full-history discovery (README-001/047, PM-004, PM-051..053),
the regime-of-discovery sub-claims under the D3/D5/D12 within-year designs (PM-019..028, PM-065..085), pool sizes and
the pre-registered strategy search (C-006, PREREG-001), the stress test under Andrews-Kim (PAPER-169/170), the ML gate
on PIT pools (PAPER-161..163), the large-n persistence and multivariate PIT results (FINDINGS-098/099/140). Also
worth reporting now, with their caveats: D11 (production screen size), D13 (power of recent-window tests), the
calendar-padding artifact (C-008, REPLICATED), the prefix-invariance demonstration of whole-history leakage.

## Not worth reporting (CUT, 120)
Comparison arms run on old small pair sets (KVUE/KMB, PNC/ZION, 21-29-pair manifests) before WRDS or before the
2026-10 fixes, engineering fixes, and anecdotes that cannot be re-derived (the early '4 of 32 |z| > 10' set). They stay
in FINDINGS / Development.md as history; they should leave PAPER.md / README unless re-run.

## Next
1. Literature: 46 claims checked against primary sources (agent running); verdicts added when it reports.
2. Apply the 90 edits: factual corrections in README / CONTRIBUTING / ERRATA / DATA_SOURCES / CLAIMS_REGISTRY /
   PROCESS_OUTLINE / PREREGISTRATION; PAPER.md and PAPER_MAGNITUDE.md edits drafted for Ross (decision 4).
3. After the chain: re-derive the 150 central claims; register each in CLAIMS_REGISTRY before it is cited.
