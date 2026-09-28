# What held up in the scrutiny — and what deserves a deeper dive (2026-09-28)

Ross (2026-09-27): "with the scrutiny check let's also see where we were successful and it may be worth to delve
even deeper into something." Source: `docs/PAPER_SCRUTINY_2026-09-27.md` (284 claims: 44 STANDS, 109 QUALIFY,
115 WITHDRAW, 8 REPLACE, 8 UNVERIFIED) plus this session's corrected results (CR-1..CR-7) and data-layer findings.
These are **proposals for Ross's buy-in** (methodology is his call); nothing below has been started.

## The pattern

What survives is the **statistics and methodology**; what fails is almost everything that is a **P&L number** (the
accounting was wrong until `pnl_dollar.py`) or a **"point-in-time" label** (candidate pools used future information).
That is a coherent story in itself: the project's measurement work is sound, and its trading conclusions were
built on a broken P&L and a leaky selection step — both now fixed and being re-run.

## What stands (checked; no confirmed defect bears on it)

1. **Durability vs currency (P-009, P-073/074, P-076).** NTRS/STT: full-sample Engle-Granger p ≈ 0.00005 over 13,373
   daily obs since 1972 on CRSP total return, but p = 0.561 on the last five years; three negative controls; SHW/UNP
   honestly reported as not replicating. The production `_eg_worker` is used unmodified.
2. **Calendar-padding artifact (P-023, P-090..092).** The exact bound (n−1)/√n = 15.81 at n = 252 for a z-score over
   a calendar-padded window, with 4 of 32 examples |z| > 10 at the market open; generalization flagged as hypothesis.
3. **Purged ML (CR-2).** With purging + 1% embargo, AUC ≈ 0.61 (RF 0.6085 [0.600, 0.616], XGBoost 0.607) for
   predicting **z-convergence** after a |z| = 1.5 crossing, 74,732 events / 1,301 pairs; linear models significantly
   worse. It does NOT predict the strategy's own trades' profitability (CR-3: AUC 0.47-0.54).
4. **Rule-invariant audit (CR-5).** The engine does exactly what the rules say (0 violations in 101,700 trades) — and
   the rules themselves are defective: 54-68% of entries at or past the stop, 32-40% stopped after a favourable move,
   19-38% re-entry within one bar of a stop.
5. **Distribution structure (CR-4).** Entries per day are negative binomial (clustered, not iid); per-pair
   convergence is beta-binomial (genuine heterogeneity, LR 495); horizon z-change Student-t (df ≈ 7).
6. **Methods notes:** the three-way power / multiple-testing / structural-break tension (P-034); DSR vs selection
   lookahead (P-131); the trade-shuffle permutation defect diagnosis (P-123); the units bug in variance (P-132).

## Deeper-dive candidates, ranked

### 1. The durability-vs-currency gap, universe-wide (recommended first)
**Why:** it is the project's most defensible finding and the natural lead of PAPER_MAGNITUDE, but it currently rests
on one showcase pair plus controls. **Deeper test:** for every pair that passes a full-sample EG screen on the
corrected WRDS universe (D17 labels fixed tonight — earlier scans tested ~2,700 wrong securities under current
tickers), measure recent-window cointegration (last 1/3/5 years) and the fraction of rolling windows significant;
report the distribution of the gap, how it relates to structural-break tests (Gregory-Hansen, Zivot-Andrews) and to
sector/era, and what a full-sample screen's "confirmed" set would have delivered out of sample. **Novelty:** a
large-sample quantification of how often full-sample cointegration is stale — directly relevant to the pairs-trading
literature, which screens full-sample (Gatev et al.; Rad-Kumar-Fisher). **Risk:** the multiple-testing / power
tension (P-034) must be handled explicitly (power-matched windows, FDR per window length). **Cost:** reuses the
episodic scan's windows; mostly analysis time.

### 2. Why convergence prediction does not become profit
**Why:** two survivors point at the same gap — purged AUC 0.61 for convergence (real signal) vs AUC ≈ 0.5 for trade
profitability, and a rule audit showing entries at/past the stop and favourable moves stopped out. The churn arms
(entry cap, directional stop, re-entry re-arm) removed exactly the defects they target and cut losses by up to
two-thirds, but made no in-sample edge. **Deeper test (pre-registered):** decompose trade P&L into (a) convergence
captured, (b) hedge-ratio drift, (c) stop/churn losses, (d) costs, and test rule sets designed from the convergence
model's own horizon and hit-rate (e.g. no stop inside the model's expected excursion) as comparison arms, on the
rebuilt pools. **Novelty:** a clean attribution of where a genuine statistical signal leaks away in execution rules.
**Risk:** easy to overfit rules — must go through the pre-registration + DSR/PBO machinery already built.

### 3. Identity contamination in ticker-keyed CRSP pipelines (tonight's D17)
**Why:** a data-quality finding with reach beyond this project: labelling CRSP securities by last-known ticker and
resolving reuse oldest-first mis-assigned 2,719 of 4,327 reused tickers (707 displacing a currently listed company);
the legacy `stocknames` table is frozen at 2024-12-31 while prices run to 2025-12-31. **Deeper test:** re-run
discovery on the corrected labels and report how many previously "confirmed" pairs were artifacts of mislabelled
securities. **Novelty:** modest as a standalone paper; strong as a reproducibility appendix / methods note.

### 4. Clustered nulls for luck checks
**Why:** entries are negative binomial, not iid, so every iid same-size null (the capital-sim luck check included)
is misspecified. **Deeper test:** block/cluster-preserving nulls; re-evaluate which "better than skipped" verdicts
survive. **Scope:** methods improvement that tightens every downstream significance claim.

### 5. Calendar-padding artifact in the wild
**Why:** stands, and the generalization to published fat tails is flagged only as a hypothesis. **Deeper test:**
replicate one or two published intraday fat-tail results with and without session-aware windows. **Risk:** needs
their data/specification; could be a short standalone note if it replicates.

## Suggested order
1 → 2 → 4 (they share the rebuilt pools and the pre-registration machinery), with 3 written up alongside the
discovery re-run (it falls out of the old-vs-new comparison for free) and 5 as an optional short note.
