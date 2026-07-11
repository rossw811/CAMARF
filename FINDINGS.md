# CAMARF — Additional Findings & Comparison Arms

**Purpose.** `PAPER.md` is kept deliberately tight around a small number of headline pillars —
per Ross's explicit direction (2026-07-11), a focused, memorable central claim beats an
info-dump. This document holds the full-depth writeups of every OTHER real, verified finding
this project has produced: comparison arms, robustness checks, negative results, and
exploratory builds that are genuine, honest, verified work — just not load-bearing for the
paper's core thesis. `PAPER.md`'s "Robustness and Comparison Arms" section (§7.15) summarizes
each of these in 2-4 sentences and points here for full detail; nothing here is hidden or
excluded from the record, it's organized by relevance to the central claim, not by quality or
confidence.

Same standards as `PAPER.md` and `Development.md` apply throughout: every finding is
independently verified (synthetic test before real data, per this project's standing
discipline), honest nulls are reported with the same care as positive results, and every
number traces to a specific script and run date.

---

## 1. When Does Added Complexity Earn Its Keep? A Cross-Method Synthesis [2026-07-11]

Five independent comparisons across this project — spanning position sizing, hedge-ratio
estimation, and portfolio concentration measurement — each pit a more sophisticated method
against a simpler alternative on the same real data. Presented together because the pattern
that emerges (four losses for complexity, one clear win) is only visible once the five are
read side by side, not scattered across separate sections as isolated results.

**Loss 1 — Hierarchical Risk Parity vs. simple risk-parity (PAPER.md §7.2).** HRP uses the TRUE
cross-pair covariance matrix and hierarchical clustering; simple risk-parity scales each
pair's position purely by its own volatility, ignoring cross-pair correlation entirely. HRP
OOS Sharpe 5.3752 vs. risk-parity's 5.8689 — the theoretically richer method loses.

**Loss 2 — Kalman slope+intercept hedge ratio vs. origin-only Kalman (Development.md, Session
27; not promoted to production).** CAMARF's production Kalman filter tracks a single state
(β only, forced through the origin); a 2-state version adding an intercept was built,
verified to correctly recover a material, real intercept on every one of 22 confirmed pairs
(|α| range 1.45–5.41 log-price units) and to produce a measurably tighter, more stationary
spread (lower standard deviation on every pair, e.g. AME/DD 0.0706→0.0269; ADF p-values improve
on 15/22, one pair moving from a borderline p=0.054 to a clearly-stationary p=0.0000) — a
textbook demonstration of omitted-intercept bias, directly against this project's own
production filter, not a synthetic strawman. Despite the corrected spread being
*statistically* better-specified on every measure, it produces a *worse trading signal*:
fixed-share Sharpe 2.35 vs. OLS's 12.28; even after normalizing position size to correct for
the two methods' different natural spread scales (a ~27,800x variance reduction that had been
silently starving the fixed-share position size of the tighter spread's real edge), Kalman
slope+intercept still underperforms, 6.08 vs. 31.96. The gap between "statistically tighter
residual" and "more profitable trading signal" is the finding — not simply "Kalman lost," but
that a real, correctly-measured statistical improvement did not translate into a trading edge,
for a mechanistically understood reason (fixed per-share commission costs are invariant to
spread scale, so a tighter spread's proportionally smaller gross P&L is disproportionately
eaten by cost).

**Loss 3 — Equal Risk Contribution vs. simple inverse-cluster-size position sizing (PAPER.md
§7.14).** ERC solves a constrained optimization (minimize variance of each pair's risk
contribution) using the correlation-cluster structure; the simple alternative just weights
inversely to cluster size. Inverse-cluster-size wins on Sharpe (0.7216) over both equal-weight
(0.7154) and ERC (0.6933) — and ERC concentrates up to 27% of the portfolio into 1-2
low-variance pairs, a real cost of the more sophisticated approach the simple scheme avoids
entirely.

**Loss 4 — Eigenvalue-penalized (continuous) position weighting vs. the same simple
inverse-cluster-size scheme (`research/eigenvalue_weighted_position_sizing.py`, new).** The
direct follow-up PAPER.md §7.2's portfolio-wide Meucci result motivates: if real correlation
concentrates in specific clusters rather than spreading evenly, why not weight CONTINUOUSLY by
each pair's loading on the dominant eigenvectors, instead of a coarser discrete cluster label?
Built by reusing `dd_hub_effective_bets.meucci_effective_bets`'s own eigen-decomposition
directly, evaluated on the same 22-pair daily P&L panel via
`portfolio_position_sizing_correction.py`'s own evaluation functions for a fair comparison.

*Design note surfaced by verification itself, not real-data testing*: a FIXED top_k is
unstable under eigenvalue degeneracy — `debug/_verify_eigenvalue_weighted_position_sizing.py`
Case 2 found a fixed top_k=2 on a fully-uncorrelated synthetic system produces wildly uneven
weights (0.333 vs 0.00003) purely from `numpy.linalg.eigh`'s arbitrary tie-breaking among equal
eigenvalues — a real risk given CAMARF's own portfolio has near-zero average correlation
(ρ̄=0.0039), meaning most real eigenvalues also cluster near 1. Fixed by adding a
Marchenko-Pastur-adaptive top_k (closed-form λ_max=(1+√(n/T))², same theoretical basis as
`analysis.py`'s `EigenportfolioDecomposer`) that selects only eigenvalues clearing the noise
band — verified to correctly fall back to equal-weight when none clear it.

*Real result*: every version underperforms. The MP-adaptive variant (only 1 eigenvalue clears
the noise band on real data) scores worst of every scheme tested (Sharpe 0.304, max weight
concentrating to 0.529 — a single dominant factor makes the penalty too crude to divide
sensibly); fixed-cutoff sensitivity variants (top_k=2,3,5) do better (0.65-0.69) but still
trail inverse-cluster-size (0.7216) and even plain equal-weight (0.7154). A fourth loss for the
more sophisticated alternative, against the exact same simple scheme that already won in Loss 3.

**Win — Meucci's eigenvalue-based Effective Number of Bets vs. Grinold-Kahn's equicorrelation
breadth (PAPER.md §7.2, portfolio-wide effective-bets result).** This is the one case in this
project where the more sophisticated method earns its complexity decisively. Grinold-Kahn
assumes a single uniform correlation across every pair and, given the portfolio's near-zero
AVERAGE pairwise correlation (ρ̄=0.0039), reports almost no diversification loss (BR_eff=19.5
of 21 nominal pairs). Meucci's eigen-decomposition instead detects that the real correlation
structure is *clustered*, not uniform — a handful of specific pair-pairs carry real
correlation (0.29-0.31) while most carry none — and correctly reports a materially lower
ENB=9.78, under half the nominal count. The simpler method's own assumption (uniform
correlation) is what fails here; the added complexity isn't decorative, it's detecting a real
structural property the simpler model is mathematically blind to by construction.

**Reading the pattern honestly, not resolving it into a false moral.** "Simple beats complex"
would overstate four losses into a general rule the fifth result directly contradicts. What
actually distinguishes the win from the losses, on inspection: in Losses 1-4, the simpler
method is not ignoring real structure — it's making a *different, adequate* simplifying
assumption (per-pair volatility scaling, origin-through hedge fit, per-cluster sizing,
discrete- vs. continuous-loading correlation weighting) that happens to interact better with a
downstream cost or estimation-noise factor the more complex method doesn't account for. In the
Win, the simpler method's assumption (uniform correlation) is actively WRONG for this
portfolio's real correlation structure, not merely less refined — complexity pays off
specifically when it corrects a false assumption the simple alternative depends on, not merely
whenever it adds more parameters. This is a useful methodological lesson for this project's own
future comparison-arm work as much as a paper finding: the question worth asking before
building a more complex method isn't "is the simpler version too crude," it's "does the simpler
version's specific assumption actually hold here" — that question, not model sophistication in
the abstract, is what predicted the outcome in all five cases above.

---

## 2. Bounded-Recent-Lookback as Primary Screen [2026-07-11]

`research/bounded_lookback_primary_screen.py` — direct robustness check on the paper's own
Strictness Paradox finding: re-screens the already-confirmed pair set using a bounded 5yr/10yr
recent window as its own PRIMARY EG+KPSS+PO test (reusing `stats.py`'s own tiering function
directly), not merely `coint_fraction_rolling` as a secondary gate on the full-sample result.

Real, small-n result: only 1 of 20 confirmed pairs has enough history for a meaningful
comparison (everything else is capped by `data.py`'s own fetch windows, correctly flagged
`is_noop`). That one pair — **7267.T/8058.T@1M, 26.4 years of history** — shows full-sample EG
p=0.0001 (gold tier) vs. **5-year-bounded EG p=0.1943, not significant at conventional levels**
(10-year-bounded: p=0.0218, still passes). A live instance of the Strictness Paradox mechanism
on a pair CURRENTLY in the confirmed set, found systematically rather than hand-picked — worth
citing alongside PAPER.md's existing NTRS/STT and SHW/UNP examples once more long-history pairs
exist to generalize beyond n=1.

---

## 3. PairCharacteristicsAnalyzer — Per-Pair Decision Trees + Archetype Clustering [2026-07-11]

`research/pair_characteristics_analyzer.py` — builds Development.md's long-planned "analyzer.py"
module (Stage 3: per-pair decision tree over entry conditions, full min-N=10/leaf +
1000-permutation + chronological-holdout discipline; Stage 4: archetype clustering on the
VALIDATED tree output, not raw features). Reuses `trades_layer1.parquet`'s already-computed
per-trade columns (`entry_z`, `half_life_at_entry`, `hurst_at_entry`, `vix_ts_regime`,
`yield_regime`) directly.

Honest, small-n result: 1,338 total trades across 24 pair-TF combos; only 14 clear the
30-trade floor to be attempted at all. Of those, 6 show at least one holdout-confirmed
characteristic. Stage 4 archetype clustering on those 6 found 3 small clusters — too thin
(n=6) to treat as real archetypes yet, same honest limitation as every other small-n result in
this project. Exploratory only, not wired into ml.py or backtest.py.

---

## 4. Regime-Conditional Entry Gate [2026-07-11]

`research/regime_conditional_entry_gate.py` — right-sized comparison arm for the "Rich Regime
Classification" plan (rule-based bucketing of a 3-level feature spec: leg Hurst, spread
velocity, macro VIX regime — not the full HMM-post-hoc-labeling rewrite).

Real result surfaced a genuine data-availability finding: `vix_ts_regime` is blank for all
1,042 trades in `trades_layer1.parquet` — macro/VIX regime conditioning is a schema field in
`backtest.py`, not actually populated by the run that produced this trade log. The GOOD bucket
(requires macro=calm) is therefore empty; the BAD bucket (trending+widening, no macro
requirement) populated with 98 trades and shows a real, directionally-consistent result:
Sharpe 6.168 vs. NEUTRAL's 9.929 and the unconditional 9.185. Separately: `hurst_at_entry`
across all trades ranges only 0.496-0.555 — production's existing Hurst gate has already
narrowed the entry-eligible population to a tight band before this script ever sees it, which
limits how much additional discrimination any Hurst-based bucketing can add downstream of that
gate. Actionable follow-up not done here: fixing `RegimeConditioner.check_entry()` to actually
populate `"vix_ts"` is a production-code change, Ross's call.

---

## 5. Earnings Blackout STORM Variant [2026-07-11]

New `earnings.py` (`EarningsCalendar`, `yf.Ticker.earnings_dates`, cached) + `backtest.py
--storm-earnings-blackout` flag: skip entries within ±3 days of either leg's earnings date.

Real result on the same 12 OLS 1h pairs used for every STORM comparison: baseline 521 trades,
Sharpe 5.4019, max drawdown $1,863.58. With the blackout: 436 trades (-16.3%), Sharpe 5.3035
(slightly worse), but **max drawdown $961.67 — 48% lower**. A genuine tradeoff, not a clean
winner: the excluded earnings-window trades were not net losers on average (removing them cost
more Sharpe than it gained) but were disproportionately the tail-risk trades. Not made the
default; available as an opt-in comparison flag.

---

## 6. ML Stage 2 (Macro-Context Ablation) [2026-07-11]

`research/ml_stage2_ablation.py` — builds `ml.py`'s own documented Stage 2 (macro context
joined onto the Stage 1 core feature set). Does not modify Stage 1's extraction; joins
`macro.py`'s regime classification onto each labeled example by `entry_time` via
`pd.merge_asof`.

Real result: macro context joins correctly (real, non-degenerate distributions across the 13
Stage 1 examples). Stage 2 is then correctly blocked by the identical `MIN_CLASS_SAMPLES` gate
as Stage 1 (13 examples, need 60) — Stage 2 adds feature columns to the same labeled events
Stage 1 has, it cannot manufacture more labeled events. Per Ross's explicit instruction, an
additional smoke test forcing training anyway (`--min-class-samples 2`) was run and its result
explicitly NOT used or cited: it crashes, because the chronological (no-lookahead) split puts
the ONLY 2 minority-class examples in the entire 13-example set at the very end of the
timeline, so the training fold contains a single class. Concrete illustration of why the
30/class gate exists, not a finding to act on.

---

## 7. Intraday Data-Quality Screen — Universe-Wide Refresh [2026-07-11]

Re-ran the existing (2026-06-23) `audit_price_degeneracy.py` fresh, extending it to 2m/3m for
the first time (previously 1m-only): 1m 31.4% flagged (446/1,422), 2m 23.5% (360/1,529), 3m
23.4% (358/1,527) — confirms the original ~32%/1m finding is durable, not a one-time artifact,
and that the "drops off sharply beyond 5m" pattern extends smoothly through 2m/3m. All 4
original BUG-D49 symbols (APAM/AZTA/INVX/NBHC) still caught. See PAPER.md's price-degeneracy
pillar for the root-cause explanation (market cap + sector) built on top of this refresh.

---

## Comparison-Arm Bias-Audit Count [Session 28, 2026-07-11]

Per this project's own bias-transparency discipline: naming the full count of comparison arms
run this session, not just the ones that showed something, whether or not each formally enters
`trial_registry.json`'s DSR accounting (that registry specifically tracks backtest-Sharpe
variants competing for production; diagnostic-only scripts below don't compete for a Sharpe
number and are correctly outside it, but are still part of this session's search in the
qualitative sense).

**Diagnostic/comparison scripts run (9):** `bounded_lookback_primary_screen.py`,
`audit_price_degeneracy.py` (re-run, 3 TFs), `price_degeneracy_root_cause.py`,
`pair_characteristics_analyzer.py`, `regime_conditional_entry_gate.py`,
`ml_stage2_ablation.py`, `eigenvalue_weighted_position_sizing.py` (4 sub-variants: MP-adaptive,
k=2,3,5), plus the two Phase 1 data-hygiene fixes that changed production numbers
(`stats.py`'s BUG-D55 fix, `decoupling_analysis.py`'s BUG-D54 fix — not comparison arms, bug
fixes, listed for completeness of "what changed this session").

**Backtest-Sharpe STORM variant added (1, DOES enter trial_registry.json):**
`--storm-earnings-blackout`.

**Production code changes (2):** `data.py` exchange-aware session handling (verified,
not yet exercised on a real fetch), `backtest.py` earnings-blackout flag wiring.
