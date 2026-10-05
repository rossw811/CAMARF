# Process paper — outline (draft for Ross's review, 2026-10-03)

Working title: **"What it takes for an AI-assisted quantitative research pipeline to produce trustworthy results:
a measured audit of one statistical-arbitrage project."**

Ross's framing (2026-10-02): the work is meant to be scrutinized — readers are invited to find holes, and every
hole found is verified and closed in the open. Ross's standing bar: novel, arXiv/PhD-level, NOT a bug-hunting log.

## Why this is a paper, not a changelog (the claims it must defend)
1. **Measured, not anecdotal.** Every failure class comes with its effect on a headline number, re-derived on real data.
2. **Generalizable.** The failure classes recur in any pipeline built the same way (ticker-keyed vendor data, rolling
   statistics, walk-forward evaluation, AI-written code); each comes with a detection test others can reuse.
3. **The protocol is evaluated, not just described.** Which checks caught which failures, which failures survived
   which checks (e.g. the 09-27 scrutiny marked C-001 "stands"; only re-derivation caught the wrong sample size).
4. **Honest accounting of AI assistance.** What the assistant introduced, what it caught, where its own summaries
   were wrong (out-of-range line numbers, wrong machine checked, wrong model counts) — from the commit and ledger
   record, not recollection.

## Falsifiable thesis
"Without (a) reproduce-first tests, (b) re-derivation of every cited number, (c) content-addressed lineage and
(d) pre-registration, the project's published headline results would have been materially wrong; each of (a)-(d)
caught at least one headline-changing failure the others missed." Refuted if any headline-changing failure was
caught by none of them, or if removing a check loses no catches.

## Sections
1. **Introduction** — reproducibility crisis in empirical finance (backtest overfitting; Bailey & López de Prado;
   Harvey, Liu & Zhu); AI-assisted research as a new failure source; contribution list.
2. **The pipeline** — data (WRDS/CRSP/Compustat, yfinance, FRED, CFTC, Binance), discovery (Engle-Granger + BH-FDR,
   episodic windows), pools, backtest, capital-constrained portfolio simulation. Enough detail to locate each failure.
3. **Failure taxonomy with measured effects** (core table; one row per class; every number from the ledgers,
   re-derived where flagged). Candidate classes and examples:
   - *Accounting:* P&L marked at spread units with drifting hedge ratio — the drift explained ALL positive P&L
     (dollar-correct Sharpes negative in-sample for every gate).
   - *Identity:* 110 Purity "pairs" were one security against itself; 2,719 of 4,327 reused CRSP tickers assigned to
     their oldest holder; stock vs futures/crypto label collisions (ES = Eversource).
   - *Calendar / time:* period-start stamps carrying period-end closes (6M bar dated Jan 1 held the Jun 30 close);
     weekend NaN rows blanking Monday returns; macro data visible before release; COT history truncated by a rename.
   - *Statistic mis-specification:* WFA Sharpe annualizing per-trade P&L by bars/year (~4.5× high); calendar-row
     sample counts (C-001: 13,373 vs 10,098); NaN fractions passing a stability filter; fail-open ML gate.
   - *Selection / lookahead:* candidate pools with future information (median eligible_from 2018 vs trades years
     earlier); quality-admission lookahead.
   - *Silent fallbacks:* 62 broad exception handlers in production modules; stale-file resume; WFA `_stale` fallback.
   - *Data fabrication:* liquidity filter forward-filling fabricated bars; cache-time forward fill; futures "roll
     adjustment" doubling real moves.
4. **The protocol** — verification loop (maker ≠ checker; reproduce first; real-data check; independent check;
   evidence travels with the claim), pre-registration with amendments committed before results, content-addressed
   lineage ("seeds"), claims registry, open hole intake.
5. **Evaluating the protocol** — for each failure: which check caught it, when, and what it would have cost if not
   caught (from the corrected-vs-original numbers). Include misses and late catches.
6. **AI assistance** — classification of failures by origin (from commit trailers and ledgers), and of catches by
   who/what caught them. Measured 2026-10-05 (`python scripts/build_attribution.py`): 163 of 188 commits carry an AI
   co-author trailer; by Python lines changed, 62% came in trailered commits (Sonnet 5 45%, Opus 5.5 9%, Sonnet 4.6
   7%) and 38% (all June-August, in large batch commits) have NO record either way. A trailer means "co-authored",
   not "wrote these lines"; state claims at that strength. (An earlier draft of this outline said "most history has
   no model trailer" -- wrong: by commits 13% have none, by lines 38%.)
7. **What survived** — the claims that replicate on corrected data (claims registry REPLICATED entries only).
8. **Limitations** — single project; licence limits on data sharing (CRSP/Compustat cannot be redistributed);
   attribution gaps; the protocol's own cost.
9. **Reproducibility statement** — code public; lineage manifests; queries; free-data claims fully reproducible.

## Source material (for re-derivation, not copying)
Development.md (canonical log), docs/CODE_REVIEW_2026-09-26.md, docs/INCONSISTENCY_SWEEP_2026-09-27.md,
docs/PAPER_SCRUTINY_2026-09-27.md, docs/CLAIMS_REGISTRY.md, docs/PREREGISTRATION_STRATEGY_SEARCH_2026-09-27.md,
git history (commit trailers), debug/_verify_*.py (each fix's failing-first test).

## Tasks before drafting prose
1. **Reconcile the code-review ledger table** — 175 rows; statuses lag the prose updates (e.g. fixed items still
   marked CONFIRMED/UNVERIFIED; 120 rows never verified either way). The taxonomy counts must come from a
   reconciled table.
2. Build the taxonomy table as a data file (one row per failure: class, how detected, detecting check, date, effect
   on a headline number with before/after, evidence path) — `docs/process_paper/failures.csv`.
3. Attribution pass over git history (model trailers per commit touching each fixed defect).
4. Register every number the paper will cite in docs/CLAIMS_REGISTRY.md and re-derive it.
