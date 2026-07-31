---
name: premortem
description: Run a premortem (Gary Klein's technique — imagine the plan already failed, work backward to why) on a new CAMARF research direction, methodology, production architecture change, or PAPER.md headline claim, BEFORE building/committing to it. Adapted from https://github.com/b1rdmania/claude-premortem-skill, tailored to seed failure-reason generation from this project's own known failure taxonomy (the BUG-D registry) rather than starting cold. Trigger phrases: "premortem this", "find the blind spots", "where will this break", "premortem [claim/plan/module]".
---

# premortem

Reframes "will this work?" into "this already failed six months from now — explain why." CLAUDE.md
already documents that reframe as one of this project's best-performing habits in disguise (every
`docs/BUG_LOG.md` entry is a premortem run too late — after the code was built and trusted, not
before). This skill runs it deliberately, before commit, instead of only discovering the failure
mode during a later bug sweep.

**This is a different point in the workflow than what CAMARF already has.** The 5-lens council
(`council-quant-pm`, `council-academic-reviewer`, `council-code-quality`, `council-process-meta`,
`council-mfe-portfolio`) reviews finished work at real milestones. `adversarial-reviewer` argues
against one already-made claim or change. Both are post-hoc. This skill runs *before* anything is
built — on a plan, not a result.

## When to use

- Before building a new research methodology or `research/*.py` comparison arm — especially one
  that will influence a production decision (a new sizing scheme, a new filter, a new confirmed-pair
  screening step).
- Before a production architecture change to `data.py`/`analysis.py`/`backtest.py`.
- Before finalizing a PAPER.md headline claim or promoting a `docs/FINDINGS.md` entry into PAPER.md.
- Before trusting a new confirmed-pair set or full-pipeline run as the basis for further work (the
  pair-set collapse this session found is exactly the kind of thing a premortem run against the
  ORIGINAL 26-pair result might have caught earlier — worth this session's Development.md entry as a
  literal training case for what a real failure reason above looked like, once this skill exists).

**Not for**: routine bug fixes (`verify-new-module`'s synthetic-test-first sequence already covers
that ground), vague/unscoped ideas with nothing concrete yet to premortem, single-answer factual
questions, or as a substitute for the council review at an actual milestone.

## The sequence

1. **Gather minimum context.** What is the plan/claim/module, specifically? What would "it worked"
   look like (a specific number, a specific behavior, a specific claim holding up)? Scan the relevant
   files/Development.md entries/dedicated_pass.md scoping first — don't ask the user for context
   that's already written down.

2. **Set the frame.** State explicitly: "It is [N months] from now. This has failed." Not "might
   fail" — assume it already has, and the job is explaining why, not whether.

3. **Generate failure reasons — seeded from CAMARF's own known taxonomy first, then open.** Before
   brainstorming cold, run the plan/claim against this project's own recurring failure classes (see
   `docs/BUG_LOG.md` for the full registry; check each explicitly against the current plan):
   - Point-in-time/lookahead bias (a computation that looks causal but isn't — BUG-D74, BUG-D75,
     BUG-D78, BUG-D80, Tier 3 generally).
   - Survivorship / universe-construction bias (current-constituent-only bias, delisted-symbol
     handling).
   - In-sample circularity (fit and score on the identical sample — BUG-D76, Tier 3.3).
   - Data contamination at an append/seam boundary (split-adjustment seams — BUG-D65, BUG-D73;
     cache-append contamination).
   - Gap-handling mismatched to the test type (bridging a routine closure is fine for a level test,
     wrong for a lag-sensitive one — the "refined risk classification" in
     `docs/GRAND_SWEEP_BUG_AUDIT_2026-07-20.md`).
   - Multiple-testing / data-mining bias not actually corrected for (BUG-D59-class pooling errors,
     FDR/BH-Y correction gaps).
   - "Same bug fixed once, not propagated to a sibling" (recurred at least 8+ times this project's
     history — check whether this plan duplicates logic that already has a known-fixed twin
     elsewhere).
   - Windows case-insensitive path collisions (BUG-D67/A14-class) if the plan writes any new output
     file keyed by a timeframe label.
   Then generate additional failure reasons freely, beyond this seed list, grounded in the SPECIFIC
   plan's own details — not generic risk-checklist language.

4. **Deep-dive each failure reason, one at a time.** Dispatch one `Agent` call per failure reason
   (`general-purpose` or `adversarial-reviewer`, whichever fits), run **sequentially, not in
   parallel** — this project's standing convention (dedicated_pass.md §11.9 flags parallel
   agent-orchestration as a real, undiscussed change from the "one agent at a time" default; this
   skill does not make that call silently just because the tooling supports it). Each dispatch gets:
   the full plan context, the premortem frame, and its ONE assigned failure reason — and must
   return: a concrete failure story (what specifically broke, in CAMARF's own terms — which script,
   which computation, what a `debug/_verify_*.py` test or a `latest_run_*.log` anomaly would have
   shown), the underlying assumption that turned out false (one sentence), and 1-2 observable early
   warning signs someone could actually have checked for beforehand.

5. **Synthesize.** Most likely failure. Most dangerous failure (highest impact, not highest
   probability — these can differ). The single hidden assumption connecting the most findings.
   A revised plan, concrete and mapped to the specific scenarios raised (not generic caution). A
   pre-launch checklist of 3-5 items, each one an ACTUAL CAMARF verification mechanism already in
   place (a specific `debug/_verify_*.py` test to write, a specific real-data re-check, a specific
   `docs/BUG_LOG.md` cross-reference) — not abstract advice.

6. **Output.** Write a markdown file to `docs/premortems/premortem-<slug>-<YYYY-MM-DD>.md` (matching
   this project's markdown-based documentation convention — Development.md, docs/FINDINGS.md,
   docs/BUG_LOG.md are all plain markdown, not standalone HTML) containing the full synthesis and
   each failure-reason deep-dive. Then give a short (3-sentence) chat summary: the most likely
   failure, the hidden assumption, and the single most important plan revision. If the premortem
   subject is itself heading toward a Development.md entry later (a new module actually gets built,
   a claim actually gets promoted to PAPER.md), reference the premortem file from that entry.

## What NOT to do

- Don't run this on something already built and trusted — that's the council's or
  `adversarial-reviewer`'s job, not this one.
- Don't skip step 3's seeded taxonomy check to save time — the whole point of tailoring this to
  CAMARF is that it shouldn't have to rediscover failure modes this project has already paid to
  learn once.
- Don't silently parallelize step 4 — if parallel dispatch is genuinely wanted for a specific
  premortem run, say so explicitly to the user first (this is the §11.9 orchestration question,
  still open).
- Don't generate a checklist of generic risk-management platitudes in step 5 — every checklist item
  must name a specific, already-existing CAMARF verification mechanism.
