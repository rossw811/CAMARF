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

## 8. Standalone ADF as a 4th Confirmatory Tier — Redundant With PO, Not Adopted [2026-07-13]

Ross's question: should a standalone Augmented Dickey-Fuller (ADF) test be added to `stats.py`'s
existing EG+KPSS+PO confirmatory tiering (§6.1)? CAMARF already relies on ADF-family logic
pervasively without ever running a *standalone* ADF directly on the spread — EG's own second step
is itself an ADF-type test on the cointegrating residual, Zivot-Andrews is literally "ADF with one
structural break," and Phillips-Ouliaris's Z_t (the existing third tier) is a closely related
residual unit-root test (Phillips-Perron on OLS residuals). The expectation stated before building
this: a standalone ADF is cheap to add but likely highly correlated with the existing PO test,
since both are residual/spread unit-root tests from the same statistical family — measured
directly rather than assumed.

**Method** (`research/adf_confirmatory_tier.py`): `statsmodels.tsa.stattools.adfuller` run
directly on each confirmed pair's real, gap-masked spread series (same source data PO/KPSS
already use), AIC lag selection, threshold p<0.10 matched to PO's existing bar for the same test
family. Verified first against synthetic ground truth (`debug/_verify_adf_confirmatory_tier.py`,
3/3 cases pass: stationary AR(1) correctly confirms at p≈0.0000, a random walk correctly does not
at p=0.9971, and the reject-null-means-stationary direction convention is explicitly confirmed
correct, not assumed).

**Real result, all 26 confirmed pairs**: **100.0% ADF/PO agreement — zero disagreements.** 25
pairs where PO already confirms show ADF agreeing at p≈0.0000; the one pair where PO does not
confirm (7267.T/8058.T@1M, the international pair already flagged elsewhere in this project as
having limited monthly bar depth) has ADF agreeing it does not confirm either (p=0.211). The
zero-disagreement outcome was checked for a real mechanism, not just reported as a bare number:
ADF (parametric — whitens serial correlation via lagged difference terms) and PO's Phillips-Perron
approach (non-parametric — a kernel-based long-run-variance correction) are two different
*estimation strategies* for testing the same null hypothesis on the same residual series; at the
sample sizes available here (hundreds to thousands of bars per confirmed pair), both are expected
to converge to the same asymptotic conclusion whenever the true spread is clearly on one side or
the other of the stationarity boundary — meaningful ADF/PO disagreement is a borderline-case
phenomenon (a test statistic sitting near its critical value), and none of CAMARF's 26 confirmed
pairs currently sit in that borderline zone. There was no disagreeing case to investigate because
none exists in the current confirmed set — a real, checked absence, not an unexamined one.

**A real secondary finding, worth flagging on its own**: naively counting ADF toward the existing
tier logic (n_confirm ≥ 3 → Gold) would shift 8/26 pairs from Silver to Gold — but every one of
those 8 pairs already has PO confirming, and ADF's own verdict is 100% redundant with PO's on this
data. Adding ADF as counted evidence would silently double-count the same underlying stationarity
test as if it were two independent confirmations, inflating apparent confirmation strength without
any genuinely new evidence behind it.

**Recommendation: do not add ADF to production tiering.** It provides zero independent
confirmatory information beyond the existing PO tier on CAMARF's current confirmed-pair set, and
using it to bump tier counts would be a real methodological error (double-counting), not a
strengthening of the tiering system. This is reported as a clean, honest negative result, not a
failed feature — per this project's rule 8, a negative result with a well-understood mechanism
(here: two tests from the same statistical family converging when the underlying signal is
unambiguous) is exactly as valuable as a positive one. Full data: `output/research/
adf_confirmatory_tier.parquet`.

---

## 9. HMM/GMM/Kalman+K-Means Regime Discovery on Trade-Timing Features — A Real Lead, Not Yet Robust [2026-07-13]

Extends Session 13's already-validated HMM regime work (fit on daily macro series: VIX/
yield-curve/COT) to trade-LEVEL entry-time features — discovering regime structure empirically
from CAMARF's own real 2,168 trades (`trades_layer1.parquet`) rather than only using predefined
macro buckets. Per-trade features are genuinely causal (macro series ffilled to entry_time only,
never using future-dated rows; cyclical hour-of-day/day-of-week encodings) — three unsupervised
methods compared on the same feature space: Gaussian HMM (sequence/transition-aware), GMM
(static), and Kalman-smoothed VIX + k-means.

**Real result.** GMM and Kalman+k-means both independently surface a cluster centered on entries
near market open (mean hour≈9.5) with markedly better realized performance than their other
discovered states — GMM: win rate 0.737 / Sharpe-like 9.98 (vs. 0.533/5.39 and 0.466/7.28 for
its other two states); Kalman+k-means: win rate 0.742 / Sharpe-like 11.97 for its best state.
HMM's three states are far less differentiated (Sharpe-like 9.50/9.03/7.10) — its
transition-persistence assumption appears to smooth over a pattern the other two, which don't
assume temporal persistence, pick up directly. Critically, mean VIX across every discovered
state in all three methods sits in a narrow 13.9–18.2 range — this is NOT a rediscovery of the
known VIX-crisis/VIX-calm effect (Session 13); if real, it's a genuinely different axis
(session-timing, not macro regime).

**Mechanism check against an existing, seemingly-related finding.** PAPER.md §7.4 already tested
session-timing directly (`session_edge`, which skips entries in the literal 9:00–9:30 ET window)
and found it "no longer a consistent win" (−0.04 Sharpe). This new cluster centers ON hour≈9.5
(at/just after the open), not inside the window `session_edge` excludes — the two findings are
not necessarily in tension, but the exact minute-level entry-time distribution within the
discovered cluster hasn't been checked against `session_edge`'s specific window boundary, which
is a concrete, unresolved follow-up before this is trusted at face value.

**The decisive caveat — tested directly, not assumed away: this structure is not robust.** An
expanding-window causal-stability check (real trades, not a synthetic case) asks whether an
early trade's discovered state stays the same whether the model is fit on all 2,168 trades or
only on the data available up to an earlier checkpoint. Real result: agreement oscillates
43.1% → 100.0% → 50.2% → 100.0% across four checkpoints — materially unstable, not a settled
pattern. The clustering is sensitive to exactly how much data it's fit on.

**Honest conclusion.** A real, non-macro-regime lead — entries near market open cluster with
better realized performance across 2 of 3 independent unsupervised methods — that is genuinely
new, not confirmatory of already-known structure. But the same investigation that found it also
found it isn't stable under refit, which is real, disclosed grounds for caution. Reported as an
open, partially-promising lead needing a proper robustness check (bootstrap resampling, or
restricting to only the OOS-holdout trade subset) before being treated as settled — not
suppressed, not oversold. Verified via `debug/_verify_hmm_gmm_regime_features.py` (3/3 synthetic
cases pass: causal-construction check, known-regime-separation purity check, stability-check
machinery sanity check) before any real-data number was trusted. Full data:
`output/research/hmm_gmm_regime_trade_features.parquet` + `_stability.parquet`.

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

---

## 10. Portfolio Risk-Management Comparison Arms: Stop-Loss Sweep and Correlation-Aware
Exposure Caps [2026-07-13]

Two of four originally-scoped comparison arms (see Development.md for the honest scope note on
the other two, volatility-targeting sizing and drawdown-triggered de-risking, not reached this
pass). Both built with full synthetic verification before real data
(`debug/_verify_stop_loss_correlation_caps.py`, 3/3 cases pass) and reuse existing CAMARF
machinery rather than reimplementing it — `sensitivity.py`'s config-patch pattern for the
stop-loss sweep, and `dd_hub_effective_bets.py`/`portfolio_effective_bets.py`'s already-computed
real correlation matrix plus `backtest.py`'s own HRP hierarchical-clustering linkage machinery
for the correlation-cap grouping.

**A real bug found as a byproduct, not the point of this investigation, but disclosed
regardless.** `sensitivity.py`'s `_portfolio_sharpe()` pools daily P&L via
`groupby(date).sum()` — the exact convention mismatch BUG-D62 already found and fixed in
`portfolio_sim.py` this session (drops zero-P&L calendar days rather than zero-filling them via
`resample("1D")`, inflating the Sharpe). That fix was never applied to `sensitivity.py`. This
means **§7.8's existing entry/exit z-score grid, ADV sweep, and half-life ceiling sweep in
PAPER.md may all be computed under the same inflated convention** — not verified or corrected
here (out of this task's scope), but flagged explicitly as a concrete item for the bug-sweep
task (#18/Phase 9) to check and, if confirmed, re-run. This investigation's own stop-loss sweep
uses a locally-defined `_correct_portfolio_sharpe()` (the proper `resample("1D")` convention)
instead of importing the buggy function, specifically to avoid reporting an inflated result.

**Part 1 — Stop-loss sweep, real result, current production default is not the best value
tested.** `config.py`'s `COARSE_STOP_ZSCORE = [3.0, 3.5, 4.0, 4.5]` grid existed but had never
actually been run. Real OOS result across all 24 confirmed pairs (corrected Sharpe convention):

| STOP_ZSCORE | Sharpe | n_trades | stop_exits | total_pnl |
|---|---|---|---|---|
| 3.0 | **5.5128** | 303 | 176 | $73,239.60 |
| 3.5 (production default) | 5.1520 | 222 | 93 | $72,895.79 |
| 4.0 | 5.1530 | 177 | 47 | $74,156.60 |
| 4.5 | 5.1278 | 161 | 30 | $73,690.76 |

A tighter stop (3.0) beats the current production default by +7.0% Sharpe (5.5128 vs. 5.1520),
with materially more trades (303 vs. 222, nearly all the extra trades being stop-outs rather
than mean-reversion exits) and marginally higher total P&L. Mechanism, worth investigating
further rather than assumed: a tighter stop generates more, smaller-loss stop-outs instead of
fewer, larger-loss ones, which — combined with real trades that continue toward mean reversion
after a would-have-been-stopped excursion under the looser convention — nets to a better
risk-adjusted outcome. Not yet promoted to production; this is a real, verified, single-pass
result on the current 24-pair set, not yet cross-checked against Phase 8's expanded-universe
confirmed-pair set or a walk-forward-style robustness check across multiple periods, both real
follow-ups before adopting 3.0 over 3.5 as the default.

**Part 2 — Correlation-aware exposure caps, honest null on the current pair set.** Reused the
real, already-computed 21-pair portfolio correlation matrix (the same one behind PAPER.md
§7.2's Meucci ENB=9.78 finding). Hierarchical clustering at corr_threshold=0.5 finds **zero
multi-pair clusters** among the 21 pairs with recorded trades (the DD-hub cluster's 5 pairs have
zero recorded OLS trades, per the existing §7.2 finding, and so are excluded from this
trades-based analysis entirely — consistent with, not contradicting, that prior finding).
Baseline and correlation-capped Sharpe are therefore identical (5.2155 both) — the cap mechanism
is real and verified (synthetic test confirms it correctly groups and caps a genuinely
correlated synthetic cluster), but it doesn't bind on the current 21-pair trading set because no
pair-pair correlation in that set actually exceeds the 0.5 threshold. Worth re-testing at a
lower threshold or once DD-hub pairs generate real trades (their own separate, already-known
concentration problem, §7.2), not a failure of the mechanism itself.

**Scope note, stated plainly per this task's own directive to report unambiguously.** Two of the
four originally-requested comparison arms were not reached in this pass: volatility-targeting
position sizing (distinct from the existing risk-parity per-pair inverse-vol scheme in that it
would target a portfolio-level volatility band) and drawdown-triggered de-risking (a causal
rule reducing size after realized drawdown crosses a threshold). Both require modifying
`backtest.py`'s actual event-driven trading loop (not just a config-patch, which sufficed for
the stop-loss sweep) — real, non-trivial builds queued as genuine follow-up work, not silently
dropped.

Files: `research/stop_loss_correlation_caps.py` (new), `debug/_verify_stop_loss_correlation_caps.py`
(new, 3/3 pass), `output/research/stop_loss_sweep.parquet`, `output/research/correlation_clusters.parquet`
(both new).

---

## 11. Lead-Lag Search Methodology Validated via Full +/- Sweep — Machinery Is Sound [2026-07-13]

**Question.** Every existing lead-lag module (`lead_lag_scan.py`, `near_miss_lag_scan.py`,
`lag_aware_cointegration_discovery.py`) collapses its internal lag search down to a single
reported "best lag," never a full profile. Three independent prior modules on this universe all
converged on a null result (no exploitable lag structure). Before trusting that convergence,
this checks whether the underlying search machinery itself is correct — a real methodology bug
(sign convention, off-by-one, misaligned indexing) could in principle produce a false "no
structure" conclusion regardless of what's actually in the data.

**Method.** `lagged_corr_scan()` (`lead_lag_scan.py`) already computes a full
`{lag: (corr, n)}` dict for `lag ∈ [-max_lag, max_lag]` internally — never previously surfaced
past its collapse to a single point. `research/lag_sweep_validation.py` reuses that function plus
`_eg_pvalue()` directly (no reimplementation) and reports the full profile — correlation AND EG
p-value at every lag, both directions — instead of collapsing it.

**Synthetic verification, designed around an already-known pitfall.** A prior module's docstring
(`lag_aware_cointegration_discovery.py`) records that a shared-random-walk synthetic construction
does not give a present/absent split at the true lag: `W[t]-W[t-k]` is itself stationary for any
fixed `k`, so nearby lags show real but progressively weaker signal. The correct assertion is
"true lag = argmax" (sharpest signal), not "true lag = only lag with any signal."
`debug/_verify_lag_sweep_validation.py` (4/4 pass): true lag +5 recovered as argmax with EG
p-value ≈0 at the true lag vs. 2.9e-05 twelve lags away (confirms sharpness, not just direction);
true lag 0 recovered; true lag −7 (B leading A) recovered, ruling out a direction bias; two
independent random walks show only modest argmax |corr| (0.11), not spuriously inflated.

**Real-data result.** 24 known-confirmed 1h pairs (positive control, pulled from the last
complete `analysis.py` output — the manifest was mid-refresh from a concurrent background
pipeline run at the time, disclosed rather than silently substituted) plus 8 comparison pairs (2
real near-miss pairs already flagged by the pre-expansion `near_miss_lag_scan.py` output, 6
hand-picked cross-sector pairs). **24/24 (100%) confirmed pairs show lag 0 at or within 3 lags of
the |corr| peak**, mean EG p-value at lag 0 = 0.0001, broadly significant across nearby lags too
(expected under the sharpness property, not a red flag). Comparison group: 6/8 (75%) also
lag-0-peaked — several "arbitrary" cross-sector pairs turned out to have real moderate
correlation (QQQ/GS: 0.646). The two non-lag-0 cases are informative, not concerning: CVSA/STEP
(argmax lag +4) exactly reproduces its already-known near-miss signal, consistent with its
already-established EG-test failure (eg_p=0.608, eg_perm_p=0.831 — real correlation lift, no
cointegration); DUK/MTSI's off-peak result (|corr|=0.04, boundary lag) is consistent with noise.

**Conclusion, stated plainly.** No methodology bug found. The search machinery correctly
recovers lag 0 as the peak with a 100% hit rate on pairs already known to be lag-0-cointegrated.
This is real, direct, positive evidence — not merely an absence of a found bug — that the three
prior independent null lead-lag results reflect a genuine absence of exploitable lag structure in
this universe at 1h, not a silent implementation defect. The universe-wide, all-timeframe
near-miss rerun (task #53, in progress) inherits real confidence in the underlying search from
this result, not just an assumption it was fine.

Files: `research/lag_sweep_validation.py` (new), `debug/_verify_lag_sweep_validation.py` (new,
4/4 pass), `output/research/lag_sweep_validation_{confirmed,comparison}_1h.parquet` (new).
Full mechanism write-up: Development.md, "Task #52" (2026-07-13).

## 12. Profit-to-Drawdown Ratio and Calmar Ratio — the Sizing-Method Ranking Is Not Metric-Invariant [2026-07-14]

**Question.** Ross's framing: the best Sharpe isn't the live strategy's priority — P&L at a
manageable drawdown matters more. Does ranking CAMARF's existing sizing-method comparison by a
drawdown-aware metric instead of Sharpe change which method looks best?

**Method.** Two new metrics added to `portfolio_sim.py`, both operating on `replay_portfolio()`'s
existing realized equity curve: `max_drawdown_pct()` (standard running-peak-to-subsequent-trough
percentage, not a global-min-vs-max reading, which would understate a real drawdown occurring
before the series' eventual high), and from it, **PDR = Profit Factor / Max Drawdown %** and the
textbook **Calmar = Annualized Return / Max Drawdown %** (using the same `resample("1D")`
annualization convention already established for Sharpe by BUG-D62/D64 — deliberately distinct
from `backtest.py`'s pre-existing `compute_metrics()` "calmar" field, which is `total_pnl/max_dd`
in raw, non-annualized dollars, a different and non-standard construction).

**Verified first.** `debug/_verify_pdr_calmar.py`, 3/3 synthetic cases pass: a known equity path's
PDR matches its exact hand-computed fraction (3105/121 = 25.6612); a monotonically-increasing
equity curve correctly returns NaN for both ratios (no silent divide-by-zero); an all-loss trade
set correctly returns 0.0 (a real, meaningful worst case) rather than NaN masking it as missing
data.

**Real result**, all 7 existing sizing methods, 2,168 real trades, $100,000 account:

| sizing_method | sharpe | max_dd_pct | pdr | calmar |
|---|---|---|---|---|
| fixed | 5.6123 | 0.0263 | **303.98** | 17.08 |
| equity_proportional | 4.7615 | 0.0275 | 253.62 | **20.20** |
| flat_2pct | 2.4837 | 0.0688 | 81.60 | 9.08 |
| quarter_kelly | 2.0403 | 0.1020 | 61.89 | 7.70 |
| third_kelly | 1.8913 | 0.1020 | 58.33 | 7.67 |
| half_kelly | 1.8915 | 0.1020 | 67.02 | 7.55 |
| full_kelly | 0.3147 | 0.4564 | 3.58 | 0.68 |

(`quarter_kelly`'s Sharpe of 2.0403 and n_taken of 104 exactly reproduce the already-on-record
BUG-D62/D64-corrected figure — a positive cross-check that this new code path is consistent with
the existing fix, not a second implementation quietly drifting from it.)

**The ranking is not metric-invariant.** `fixed` wins on both Sharpe and PDR — consistent with each
other. But `equity_proportional` wins on Calmar despite a worse Sharpe and PDR. Mechanism, checked
directly: `equity_proportional` finishes with a HIGHER final equity (508% total return) than
`fixed` (356%) at a nearly identical max drawdown (2.75% vs. 2.63%) — Calmar rewards the larger
compounded return directly. Sharpe measures the mean/std of DAILY P&L, a consistency metric rather
than a magnitude-of-compounding one: `fixed` takes far more trades (1,313 vs. 801, since
equity-scaled sizing changes which trades clear the capital-availability check) at steadier
position sizes, giving smoother day-to-day P&L. Both readings are correct simultaneously — they
answer different questions (return magnitude vs. return consistency) — and this is a genuine
divergence between the two drawdown-aware metrics themselves, not just between either of them and
Sharpe. Which metric gets reported can itself change which sizing method looks best, independent of
whether drawdown is considered at all.

Files: `portfolio_sim.py` (4 new functions), `debug/_verify_pdr_calmar.py` (new, 3/3 pass),
`research/pdr_calmar_comparison.py` (new), `output/research/pdr_calmar_comparison.parquet` (new).
Full write-up: Development.md, "Task #49" (2026-07-14).
