# CAMARF Handoff — End of Session, 2026-07-20

**Superseded document notice**: everything below replaces the previous version of this file (written
2026-07-10, end of "Session 27"). That version is now badly stale — the confirmed-pair-set reality it
assumed no longer holds, and a huge amount of work has landed since (the full Phase 1-18 plan at
`~/.claude/plans/read-development-and-paper-mossy-boot.md`, the PAPER.md rewrite, the pair-selection
lookahead investigation, and today's FDR-method-comparison closure). Read this file, not memory of the
old one.

**Read `CLAUDE.md` first, in full**, before touching anything — non-negotiable architecture rules,
working-style conventions, and the "Current State" section. This handoff assumes you've read it.

---

## The single most important thing to know before doing anything else

**The historically-reported confirmed-pair set (26 pairs, IS Sharpe 5.80, OOS Sharpe 5.22 — the
numbers still headlining PAPER.md's Abstract and §3/§5/§6/§7 as of this writing) does not currently
exist on clean data.** A fresh, definitive `analysis.py --timeframes 1h` rerun this session found
**0 confirmed 1h pairs** after the full screening funnel, and this was NOT left as an unexplained
anomaly — it was root-caused, proven, and independently corroborated:

1. The historical 26-pair result depended on DD's cache carrying an unreconciled ~3x split-adjustment
   contamination (BUG-D65, already fixed this session), which produced numerically-degenerate raw EG
   p-values (median ~1e-8, min 2.3e-25) that propped up BH-FDR's step-up rank chain, letting the old
   run's rejection cutoff extend to rank 314. Removing that contamination correctly collapses the
   confirmed set to essentially nothing — this is the mechanically correct, literature-corroborated
   consequence of removing real data contamination from a rank-dependent multiple-testing correction,
   **not a new bug**.
2. Today's follow-up work closed the one remaining open question from that investigation ("is BH-FDR's
   rank-chain sensitivity itself the problem — would a different correction method recover the real
   pairs?"). Built and ran a 4-method comparison (step-up BH, Benjamini-Yekutieli, two-stage TSBH,
   fixed Bonferroni) on the full current-universe raw p-values (m=36,753): **none of the 4 methods —
   including Bonferroni, which has zero rank-chain dependency — recovers any of the 8 previously-
   flagged real-but-moderate pairs** (LNT/VTR, LNT/WELL, CMS/DUK, EG/WRB, HAL/NOV, MET/TMHC, PFG/STLD,
   UMBF/FHB). Two further legitimate recovery attempts (an independent Johansen+KPSS confirmatory
   test, and a same-GICS-sector-restricted rescan) also do not recover them — see "Today's work" below.
   **This question is now closed with a definitive negative, not open.**
3. Net result across the whole universe: only 2 economically real survivor pairs anywhere
   (FELE/MAS, PNC/ZION — plus SPY/VOO, a known index-tracking artifact already excluded downstream by
   `CrossAssetTagger._is_index_tracking_pair` regardless of surviving FDR).

**PAPER.md has NOT been reconciled to this yet.** The reconciliation text is fully drafted in
`docs/PAPER_PENDING_CHANGES.md` entry #7 (marked "HIGHEST PRIORITY IN THIS FILE"), but per this
project's standing rule, PAPER.md/README.md are never edited directly without Ross's explicit review —
that review has not happened. **Do not treat PAPER.md's current headline numbers as current truth.**
If your task touches PAPER.md's pair-count/Sharpe claims, read `docs/PAPER_PENDING_CHANGES.md` entry #7
in full first, and raise the reconciliation decision with Ross rather than silently propagating either
the stale 26-pair number or the new near-zero one.

Full technical detail, verification chains, and citations: Development.md, search for "Confirmed-pair-
set blocker RESOLVED", "Ross explicitly distrusted the 0-confirmed-pairs finding", and "Both remaining
'recover the pairs, scientifically' avenues built and run" (all dated 2026-07-14 through 2026-07-20).

---

## Today's work (2026-07-20) — what actually happened this session

Short session, entirely follow-up to the pair-set investigation above (no new pipeline runs, no code
changes to production files):

1. **4-method FDR comparison** (`research/fdr_method_comparison.py`) — closed the "is a different
   correction method the fix" question. See above.
2. **Johansen + KPSS confirmatory cointegration check** (`research/confirmatory_cointegration_check.py`)
   — an independent test family (VECM-rank-based, not EG's OLS-residual-ADF) run on the 8 target pairs
   plus 3 positive controls (already-FDR-confirmed pairs) and 4 negative controls (decisively
   non-cointegrated pairs, raw p=1.0). Result: Johansen finds a cointegrating relationship in **all
   8/8 target pairs** and correctly finds nothing in **0/4 negative controls** — real, disclosed
   evidence these pairs are not pure statistical noise. KPSS (stricter, opposite-null test) agrees on
   only 3/8. **This does not change the confirmed-pair set** — it's supplementary evidence about
   signal quality, consistent with CAMARF's own §4.1 confirmatory-tier design, not a route around FDR.
3. **Sector-restricted FDR rescan** (`research/sector_restricted_fdr_rescan.py`) — restricted the
   candidate universe to same-GICS-sector pairs only (Gatev/Goetzmann/Rouwenhorst 2006 convention),
   reusing the already-computed raw p-values under a smaller m (36,753 → 13,799). Still recovers
   nothing — the restriction only shrinks m ~2.7×, nowhere near the ~26-100× these p-values would need,
   and 4 of the 8 target pairs are cross-sector and structurally untestable by this rule at all.
4. **`.gitignore` fixed a 3rd time** for the same recurring bug class (root-level scratch `*.log` files
   slipping through session-specific ad-hoc naming conventions — documented 2026-07-11, 2026-07-15, now
   2026-07-20). Replaced the one-off suffix patterns with a robust allow-list: ignore all `*.log` at
   repo root by default, explicitly un-ignore the curated `latest_run_*.log` summaries and the small
   set of pre-existing tracked exceptions. Verified both directions with `git check-ignore -q` before
   and after. **This should not need a 4th fix** — if it does, the allow-list itself has a gap, not the
   general strategy.
5. **Recurring 30-minute status-update cron job (`f417d7d5`) cancelled** at Ross's request — do not
   expect further automated status-update prompts.

All three new `research/*.py` scripts were verified against synthetic ground-truth cases in matching
`debug/_verify_*.py` files BEFORE being trusted on real data (this project's standing discipline) — all
passed. Full write-up: Development.md, "Both remaining 'recover the pairs, scientifically' avenues
built and run — honest, converged negative result" (2026-07-20).

**Uncommitted as of session end**: `Development.md`, `docs/PAPER_PENDING_CHANGES.md` (modified),
`.gitignore` (modified), 3 new `research/*.py` files, 3 new `debug/_verify_*.py` files, 3 new
`latest_run_*.log` result summaries. Ross has not yet been asked whether to commit — confirm with him
before committing, per this project's standing "never commit unless explicitly asked" convention.
Everything prior to today (through commit `a2b2fcc0`, "7/15") is already committed.

---

## Open work — the actual current backlog

The big multi-phase plan (`~/.claude/plans/read-development-and-paper-mossy-boot.md`, "CAMARF: Deep
Reconciliation, Deeper Research, and Paper Rewrite") has Phases 1-12 complete. **Still open**:

- **Phase 13** (in progress): re-run every deferred/stale PAPER.md analysis against the FINAL confirmed-
  pair set — except the "final confirmed-pair set" this phase assumes (the post-universe-expansion,
  pre-DD-refetch 26-pair set) is now itself superseded by the pair-set collapse above. **Before
  resuming Phase 13, get Ross's direction on which pair-set reality PAPER.md should actually report** —
  re-running §7.2-§7.14's tables against a near-zero pair set may not be the right move until that's
  resolved.
- **Phase 14** (pending): caveat remediation discussion — can any of the small-n caveats be
  accommodated rather than just disclosed. Likely needs to be revisited in light of the pair-set
  collapse regardless.
- **Phase 15** (in progress): market-structure/mechanism depth pass, flesh out remaining outlined
  sections.
- **Phases 16-18** (pending): report.py visualization update, full limitations-completeness pass,
  final reconciliation. All gated on Phase 13/14 resolving first.
- **Phase 5 remnant** (in progress per task list, though the plan's own STATUS line calls Phases 1-5
  complete except two deliberately-deferred items): full repo restructure for GitHub. Check the plan
  file's Phase 5 section for the two explicitly-deferred low-value/high-risk items (Development.md
  session-archive split, `latest_run_*.log` subfolder move) before assuming this is fully done.

**Separate, older backlog items still pending** (see live task list via TaskList — 76 tasks total as of
this session, most completed): task #63 (dedicated_pass.md's relational sweep + volatility
standardization — explicitly scoped as off-limits for several recent sessions, reserved for later),
#65 (beta-neutral lag structure rabbit hole), #38 (documentation professionalism pass), #46 (the
CAPSTONE full-pipeline+all-research-scripts rerun — very large, deliberately not attempted piecemeal),
#57 (apply PairCharacteristicsAnalyzer to cross-timeframe divergence cells), #71 (IBKR real depth
ceiling for 1h equity bars found to be ~3 weeks per-request via pagination testing — the ORIGINAL "how
deep can we get 10Y history" question is still practically unanswered at that ceiling; not revisited
since).

**The most consequential open decision, not a task**: given the pair-set collapse, does Ross want
PAPER.md to (a) report the honest near-zero current-pair-set reality as its own headline finding — a
legitimate, if very different, contribution about the fragility of large-scale BH-FDR screening — or
(b) keep exploring for a defensible way to responsibly work with the 2-3 pairs that do survive, or (c)
something else. This shapes essentially all of Phase 13 onward and should be resolved before more
analysis-table reruns are attempted against a pair-set definition that may not be the final one.

---

## Standing conventions this project has already established — don't relitigate these

- Run everything via `C:\Users\RossW\anaconda3\envs\trading\python.exe`, never bare `python`.
- PAPER.md/README.md changes are drafted into `docs/PAPER_PENDING_CHANGES.md` only, never applied
  directly — Development.md gets real-time direct entries as normal.
- For long (>10 min) background jobs, use PowerShell `Start-Process -RedirectStandardOutput ...
  -RedirectStandardError ... -WindowStyle Hidden -PassThru`, not the Bash tool's `run_in_background`
  (which has silently killed jobs mid-run this project, losing completed work — see `pit_wfa.py`'s
  per-fold checkpointing, added specifically because of one such incident).
- Every new research script gets a synthetic `debug/_verify_*.py` test with known ground truth BEFORE
  being trusted on real data — no exceptions, including for "just a comparison" scripts.
- New methodology (not bug fixes) goes through Ross for explicit buy-in before being built, even under
  autonomous/auto-mode operation — see CLAUDE.md's "Working Style" section.
- Never commit without being explicitly asked, even at natural session-end boundaries.
- `dedicated_pass.md`'s own scoped items (#63, #65 in the task list) remain off-limits unless Ross
  explicitly lifts that restriction for the new session.

## Using Graphify

`graphify-out/` exists but was last built before today's 3 new research scripts. Run `graphify update .`
(AST-only, no LLM/API cost) before relying on it for navigation this session.
