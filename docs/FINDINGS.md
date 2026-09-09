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

---

## Disclosure Added Retroactively to Findings #1–12: All Predate the WRDS-Primary Universe
Transition and Cite a Confirmed-Pair Set (20-26 Pairs) That No Longer Exists [2026-08-09,
surfaced during a systematic re-verification pass]

Re-verifying every finding in this document (re-running each cited `debug/_verify_*.py` synthetic
test — all 14 checked at this point pass cleanly, no methodology bugs found at that level) surfaced
a gap of a different kind: Findings #1–12 (dated 2026-07-11 through 2026-07-14) all reference and
quote specific numbers from CAMARF's **pre-WRDS confirmed-pair set** (20, 21, 22, 24, or 26 pairs,
depending on the exact finding and date) — e.g. Finding #1's HRP/Kalman/ERC/eigenvalue/Meucci
comparisons on "the 22-pair daily P&L panel," Finding #10's stop-loss sweep "across all 24 confirmed
pairs," Finding #12's PDR/Calmar table on "2,168 real trades." **None of these findings carry a note
that this universe was real and current AT THE TIME, but is not the current production universe** —
Session 29-30 (2026-08-01 through 08-04) switched WRDS to primary for daily-and-coarser US
equity/ETF data, which collapsed the confirmed-pair set to **3 pairs** (`KVUE/KMB@3m`,
`PNC/ZION@4h`, `IQV/Q@1D`), a real, disclosed, methodology-driven change (not a data-quality
regression — see `PAPER.md` §3/§5 and `README.md`'s "Current Results"), not something that has ever
been silently reversed.

**This is the same class of gap Findings #13-19's own retroactive disclosure (below) already
covers for the Session 30 comparison arms — extended here to the earlier findings that predate even
that disclosure.** None of these 12 findings are wrong for what they measured at the time (every
cited number was real, verified against real data as it existed then, and every synthetic
`debug/_verify_*.py` test behind them re-runs clean today). But a reader encountering "24 confirmed
pairs" or "the 22-pair panel" in Findings #1-12 today, without this note, could reasonably assume
that describes CAMARF's current production universe. **It does not.** Whether any of these
comparison-arm results (HRP vs. risk-parity, the stop-loss sweep, PDR/Calmar sizing-method ranking,
regime-conditional entry gate, etc.) still hold directionally on the current 3-pair universe is an
open, real question — not yet re-tested, and likely to be data-starved at n=3 the same way Session
30's own new comparison arms were found to be (see Finding #17's SVM null: "19 examples, need 30/
class"). Re-running each of Findings #1-12 against the current universe is real follow-up work, not
attempted here — flagged as a candidate addition to the master plan's Thread C (exhaustive
parameter-sensitivity/re-verification work) rather than done piecemeal.

---

## 13. Cycle Detection (Wavelet Dominant Period, Cross-Asset Phase Sync, Cross-Timeframe
Consistency) — First Pass, Honest Null on the Only Real Pair Available [2026-08-02]

Ross asked to explore cycle detection along three axes at once, research/comparison purposes
first, no production wiring: (1) within-asset dominant cycle period via a Morlet continuous
wavelet transform, implemented directly in numpy/FFT rather than adding a PyWavelets dependency
— same "no new dependency" convention `wavelet_hurst_comparison.py` already established, for the
same documented reason (this project's history of environment/dependency pain); (2) cross-asset
phase synchronization via a rolling, **causal** Hilbert-transform phase-locking value (PLV)
between a pair's two legs; (3) cross-timeframe cycle consistency — does the same pair's dominant
cycle length agree once converted to a common calendar-day unit across timeframes.

**Verification first.** `debug/_verify_cycle_detection.py` (6/6 pass): the wavelet estimator
recovers a known synthetic period (true=40 bars, recovered=42); the PLV estimator gives 0.998 for
a synthetic phase-locked pair vs. 0.155 for independent white noise, and — the check this
project's causality audit (BUG-D99–D103) makes mandatory for anything rolling/windowed — a large
perturbation placed strictly *after* a cutoff bar leaves every PLV value *before* that cutoff
bit-for-bit unchanged, confirming `rolling_plv` is genuinely causal, unlike the wavelet dominant-
cycle series (disclosed below).

**Real-data result: KVUE/KMB, the only real confirmed pair as of Session 29, at its two confirmed
timeframes (2min, 3min).**

| pair@TF | n bars | dominant period (bars) | dominant period (calendar days) | mean rolling PLV (window=60) |
|---|---|---|---|---|
| KVUE/KMB@2min | 11,804 | 2951.0 | 15.13 | 0.411 |
| KVUE/KMB@3min | 4,159 | 677.5 | 5.21 | 0.327 |

Cross-timeframe consistency check: ratio = 2.90 (15.13 / 5.21 days), **outside the 0.5–2.0x
consistency band** — `consistent_within_2x: False`.

**Honest read, not oversold:** this is a null result on n=1 pair, not a finding to build on yet.
Two disclosed limitations make it weaker still: (a) the 2min dominant period (2951.0 bars) landed
*exactly* at the edge of the scanned period grid (`max_period_frac=0.25 * 11804 = 2951.0`) — the
estimator is reporting "the longest cycle I was allowed to look for," not a genuinely resolved
peak, so that number is an artifact of the grid bound, not real evidence of a 15-day cycle; (b)
the dominant-cycle wavelet transform itself is **not point-in-time-safe** (computed via one
whole-series FFT, so it uses both past and future data) and the PLV is computed on raw,
unfiltered returns rather than band-pass-filtered to a frequency of interest first — both are
disclosed, deliberate v1 simplifications for a research diagnostic, not something to promote to
an `ml.py` feature or live signal as-is.

**Bottom line:** no evidence yet that KVUE/KMB carries a stable, cross-timeframe-consistent cycle,
and the one number that looked most interesting (15-day dominant period at 2min) is explainable
by a grid-boundary artifact rather than a real periodicity. With only one confirmed pair to test
against, this can't be generalized either way — re-running against a larger confirmed-pair set
(once one exists) with a wider period grid and a causal, right-truncated wavelet retrofit is the
right next step before drawing any conclusion, positive or negative.

Files: `research/cycle_detection.py` (new), `debug/_verify_cycle_detection.py` (new, 6/6 pass),
`output/research/cycle_detection.parquet` (new).

---

## 14. Lévy Jump-Diffusion Test vs. GapFlag — They Detect Completely Different Things [2026-08-02]

Ross asked whether jump-diffusion (Lévy process) modeling adds anything over treating gaps as
noise, tied to the existing `GapFlag` system (`data.py`'s NONE/FILL/NO_ACTIVITY/HALT/DATA_GAP/
SPARSE classification). Built the Lee & Mykland (2008) jump test — a bipower-variation local
volatility estimator (robust to jumps, since it multiplies ADJACENT absolute returns rather than
squaring one, so a single jump return doesn't blow up its own local vol estimate) gives a jump
statistic at every bar; bars exceeding the test's exact asymptotic critical value (computed per
the paper's formula, not a rule-of-thumb threshold) are flagged. No new dependency — pure numpy.

**Verification caught a real bug before real data.** The first implementation applied the square
root to the wrong term (`sqrt(π/2) * mean(prod)` instead of `sqrt(π/2 * mean(prod))`) — bipower
variation estimates *variance*, so the sqrt must wrap the whole product. This flagged 95.5% of a
pure-diffusion synthetic series as jumps against a 1% nominal rate — an obviously broken result the
synthetic test (`debug/_verify_levy_jump_diffusion.py`) caught immediately. After the fix: 0/5000
false positives on pure diffusion, 5/5 injected large jumps recovered exactly, continuous-vol
(jump-excluded) correctly lower than total vol on a jumpy synthetic series.

**Real-data result: KVUE/KMB, both confirmed timeframes.**

| symbol@TF | jumps detected | % of bars | total_vol | continuous_vol | Δ% |
|---|---|---|---|---|---|
| KVUE@2min | 252 | 2.13% | 0.001110 | 0.000777 | −30.0% |
| KMB@2min | 183 | 1.55% | 0.001307 | 0.000967 | −26.0% |
| KVUE@3min | 167 | 4.02% | 0.001363 | 0.000788 | −42.2% |
| KMB@3min | 144 | 3.46% | 0.001693 | 0.001060 | −37.4% |

**The genuinely interesting part: 0% overlap with GapFlag, in either direction.** Every one of
these statistically-detected jumps occurred on a bar with `GapFlag == NONE` — confirmed directly
(`df["gap_flag"].value_counts()` is 100% `NONE`, 11,805/11,805 bars, for this pair/window — not an
extraction bug, the real data has no flagged gaps at all here). So GapFlag and jump-diffusion jumps
are not two views of the same phenomenon — they're answering genuinely different questions.
`GapFlag` tracks provider-side data continuity (a bar is missing, a halt occurred, volume is
degenerate); the Lee-Mykland test finds large instantaneous price *moves* within an otherwise
completely normally-reported price series. A pair can have zero data-continuity problems and still
carry 1.5–4% of its bars as statistically significant return jumps — real jump risk that CAMARF's
existing gap-handling machinery has no mechanism to see, because it was never designed to look for
that.

**Bottom line, not oversold:** jump-adjusted (continuous-only) volatility is materially lower than
the naive full-sample volatility `wfa.py`'s `garch_stop` baseline currently uses — 26-42% lower
across the four symbol/TF combinations tested. That's a real, disclosed candidate for a vol-
estimator refinement, not yet wired into production (deliberate v1 scope, per Ross's "research/
comparison sake first" framing) and tested on only one confirmed pair. Whether jump-adjusted vol
changes `garch_stop`'s actual stop-trigger behavior or backtest Sharpe in a way that matters is the
next question, not yet answered here.

Files: `research/levy_jump_diffusion.py` (new), `debug/_verify_levy_jump_diffusion.py` (new, 4/4
pass), `output/research/levy_jump_diffusion.parquet` (new).

**Update, broad-scale confirmation via `--pit-safe` [2026-08-04]:** the original result above was
one confirmed pair. Wired `--pit-safe` (task #5) to source pairs from `research/
pit_pair_discovery.py`'s episodic screen instead, and ran it against all 707 PIT-safe (pair, tf)
combinations. After the `load_aligned_pair`/200-clean-returns filter, 640 symbol@TF rows survived
across 206 unique symbols, ALL at 1D (intraday history for most PIT-safe pairs is too short/gappy
to pass at this scale — a real, disclosed data-availability constraint, not a bug). **The 0%
GapFlag-overlap finding holds exactly at this much broader scale: 640/640 rows show 0.0% overlap
between statistically-detected jumps and non-NONE GapFlag bars.** Jump frequency: mean 0.51%,
median 0.47% of bars (range 0.04%-1.64%) — lower than the original 2min/3min KVUE/KMB result
(1.5-4%) because these are all 1D bars, not intraday (fewer, larger-magnitude jumps per bar at
daily resolution is expected, not a contradiction). Continuous-vs-total vol reduction: mean -7.3%,
median -5.8% (smaller than the original single-pair -26% to -42%, again consistent with 1D vs.
intraday granularity, not a weaker effect). **This meaningfully strengthens the core claim** — "real
jump risk invisible to GapFlag" is not a KVUE/KMB idiosyncrasy, it replicates across 206 symbols
at production scale. Whether jump-adjusted vol changes `garch_stop`'s actual behavior remains the
open next question this finding was already honest about.

Files: `output/research/levy_jump_diffusion.parquet` (updated, 640 rows).

---

## 15. Is CAMARF's Realized Volatility "Rough"? Mixed Signal, Estimator Disagreement Disclosed
[2026-08-02]

Companion comparison arm to the jump-diffusion test above: Gatheral, Jaisson & Rosenbaum (2018,
"Volatility is Rough") found real-market realized volatility has a Hurst exponent around H≈0.1 —
far rougher/more anti-persistent than a standard diffusive process's H=0.5 — which would mean
`wfa.py`'s `garch_stop` baseline (built on the standard smooth/persistent-vol picture) is modeling
the wrong kind of process. Tested this directly: build a rolling realized-vol series, log-transform
(matching Gatheral et al.'s log-RV convention), then estimate its Hurst exponent with the SAME
three estimators this project already uses for spread mean-reversion quality — R/S and DFA
(`analysis.py::HurstEstimator`) and the Haar-wavelet-variance estimator
(`wavelet_hurst_comparison.py::wavelet_hurst`) — reused directly, not reimplemented, for a true
apples-to-apples reading against every other H number already in this project's record.

Verified first (`debug/_verify_rough_volatility.py`, 3/3 pass) using this project's existing
AR(1)-direction-check convention (same approach `debug/_verify_wavelet_hurst.py` already
established): a strongly mean-reverting synthetic vol process gives H well below 0.5 (0.30-0.43
across estimators), and a more persistent vol process gives a strictly higher H than a rougher one
on the same estimator.

**Real-data result: KVUE/KMB, both confirmed timeframes.**

| symbol@TF | H_rs | H_dfa | H_wavelet |
|---|---|---|---|
| KVUE@2min | 0.453 | 0.326 | 0.333 |
| KMB@2min | 0.462 | 0.275 | 0.271 |
| KVUE@3min | 0.499 | 0.377 | 0.385 |
| KMB@3min | 0.508 | 0.257 | 0.199 |

**Honest read: the three estimators disagree, and that disagreement is itself the finding.** DFA
and the wavelet estimator both land well below 0.5 (0.20-0.39) across all four symbol/TF
combinations — directionally consistent with Gatheral et al.'s rough-vol picture, though not as
extreme as their reported H≈0.1. R/S lands much closer to 0.5 (0.45-0.51), on the border between
"rough" and "not rough" — this is the SAME known R/S finite-sample upward bias
`analysis.py::HurstEstimator`'s own docstring already documents ("Slight finite-sample upward
bias"), not a new artifact of this module. Reporting all three rather than picking whichever
supports a conclusion is the honest move here, per CLAUDE.md rule #7 — a result that depended on
which of three legitimate estimators you happened to report would not be a real result.

**Bottom line, not oversold:** DFA/wavelet give real, if modest, evidence of vol roughness on
CAMARF's own confirmed pair; R/S does not clearly agree. One confirmed pair, two timeframes, three
estimators with a genuine split verdict is not enough to justify building a rough-vol-based
alternative to `garch_stop` yet — this is a candidate worth re-testing once a larger confirmed-pair
set exists, not a result to act on now.

Files: `research/rough_volatility.py` (new), `debug/_verify_rough_volatility.py` (new, 3/3 pass),
`output/research/rough_volatility.parquet` (new).

---

## 16. Options Greeks as Correlation/Convergence Features — Significant Correlation, Likely a
Price-Level Confound, Not a Clean Signal [2026-08-02]

Ross asked whether options Greeks (gamma especially) add signal to correlation/convergence
detection. `options.py` already has Black-Scholes pricing and a realized-vol IV proxy (Session
27, no paid data) — reused both directly here rather than reimplementing. **Upfront limitation,
stated in the module itself:** there is no real options-chain data anywhere in this project (no
paid data source). Every Greek here is a MODEL value from a fixed ATM (K=S), fixed-tenor
(30-day) Black-Scholes assumption fed `options.py`'s realized-vol proxy as the "implied" vol —
not a market-quoted Greek, and inheriting the same variance-risk-premium bias `options.py`'s own
docstring already discloses for that proxy.

**Verified first** (`debug/_verify_options_greeks_features.py`, 5/5 pass) against finite-difference
derivatives of `options.py`'s own already-existing `black_scholes_call()` — delta, gamma, and vega
all match their numerically-differentiated counterparts to within 1e-3, and gamma correctly peaks
ATM relative to 20%-OTM/ITM strikes.

**Real-data result: KVUE/KMB, daily, n=753 overlapping bars.** Correlation between the pair's
gamma spread (|gamma_KVUE − gamma_KMB|) and their 30-day rolling realized return correlation:
**r=0.442, p<0.0001** — statistically significant.

**Honest read: this is very likely a price-level confound, not a real convergence signal.**
Checked directly: KVUE trades around $18-24, KMB around $100+. Black-Scholes gamma scales
approximately as 1/S, so KVUE's gamma (mean 0.3185) is ~4.6x KMB's (mean 0.0698) almost entirely
because of the price-level difference between the two stocks, not because of anything about their
joint dynamics. A gamma_spread computed this way is dominated by that fixed level gap and will
track whatever else co-moves with overall market volatility regimes (which also drives realized
correlation up during stress periods) — a classic case of two variables both responding to a
common regime driver, not one causing or informing the other. The statistically significant r=0.442
should NOT be read as "gamma spread predicts pair correlation" without first normalizing gamma by
price level (e.g. dollar gamma or gamma as a fraction of position notional) and re-testing —
not done here, flagged as the honest next step rather than silently accepted at face value per
CLAUDE.md rule #7.

**Bottom line:** a real, significant correlation exists in the raw numbers, but the most likely
explanation is a shared-regime/price-level artifact rather than options convexity carrying genuine
information about co-movement. Not promotable as a feature without the normalization fix and
re-test above.

Files: `research/options_greeks_features.py` (new), `debug/_verify_options_greeks_features.py`
(new, 5/5 pass), `output/research/options_greeks_features_KVUE_KMB.parquet` (new).

---

## 17. SVM-via-Gradient-Descent Meta-Labeler Comparison Arm — Built and Verified, Real-Data Run
Blocked on Timing, Not Yet a Result [2026-08-02]

Ross's last comparison-arm request: an SVM alternate classifier for `ml.py`'s meta-labeler,
trained via gradient descent (sklearn's `SGDClassifier(loss="hinge")` — hinge loss + SGD is the
standard linear-SVM training method, the Pegasos algorithm is exactly this), A/B'd against
`ml.py`'s production XGBoost. No new dependency. Built to reuse `ml.py::build()` directly (the
real, already-persisted examples XGBoost trains on, not a separate dataset) and reproduce
`_train_and_validate`'s exact chronological-split + train-only-median-imputation convention.

Verified first (`debug/_verify_svm_gradient_descent_classifier.py`, 3/3 pass): split sizes exactly
match `Config.ML.TRAIN_PCT`/`VAL_PCT` arithmetic, median imputation is confirmed to use the TRAIN
slice only (matching the no-leakage fix `ml.py` already documents finding 2026-07-20), and the SGD-
hinge fit mechanics recover a trivially separable synthetic 3-class problem at 100% accuracy.

**Real-data run, first attempt, did not produce a comparison** — not a failure of this module, a
timing collision with the WRDS-comparison `analysis.py` re-run happening in the same session: that
run's own startup clears stale `output/results/` directories before regenerating them
(`analysis.py`'s documented "Clearing stale results: script changed" behavior), so `ml.py::build()`
found 0 confirmed pairs at the moment this was run.

**Re-run after `analysis.py` completed (2026-08-03, real WRDS-primary universe, 3 confirmed pairs)
— still insufficient data, but now for a genuine reason, not a collision.** `ml.py::build()` found 19
total labeled entry-event examples (10 `converged` / 9 `not_converged`) sourced from 1 of the 3
confirmed pairs' persisted spread series (`KVUE/KMB`; the two new pairs, `PNC/ZION` and `IQV/Q`,
produced no labeled examples yet — their confirming timeframes are 4h/1D, so entry events accumulate
slowly). `Config.ML.MIN_CLASS_SAMPLES` requires >=30 examples per class; smallest class here is 9.
Reported honestly as the expected result rather than forced — see `Config.ML.MIN_CLASS_SAMPLES`'s
own design intent. No SVM-vs-XGBoost comparison is possible until more entry-event history
accumulates across the 3 confirmed pairs, or the confirmed-pair set grows on intraday timeframes.

Files: `research/svm_gradient_descent_classifier.py` (new), `debug/_verify_svm_gradient_descent_
classifier.py` (new, 3/3 pass). No `output/research/*.parquet` — by design, there is nothing to
compare yet; re-run periodically as pair history accumulates.

## 18. Inverse-Polarity ("Polar Opposite" Equilibrium) Comparison Arm — Built and Verified, Honest
Null on the Current Confirmed-Pair Set [2026-08-03]

Ross's framing: instead of screening for pairs that move together, look for pairs whose *bounded
state* sits at opposite extremes of its own historical range (one near its rolling max exactly when
the other is near its rolling min — literal "polar opposites"), and trade a breakdown of that
expected opposite-extremes relationship as a mean-reversion/arbitrage signal.

**Key design constraint, established before building anything:** raw negative return correlation
alone does not imply a real equilibrium exists. Two assets can have return correlation near -1 while
their price levels drift apart without bound forever (independent regimes that happen to
anti-correlate over the sample). `research/inverse_polarity.py` therefore runs a two-stage screen —
(1) the existing Engle-Granger cointegration test (`statsmodels.tsa.stattools.coint`, already used
for standard pair confirmation; its internal OLS step already fits whatever hedge-ratio sign
minimizes residual variance, so a genuine negative-hedge cointegrating relationship is detectable
with the *existing* test, unmodified — nothing new needed there) applied to strongly
anti-correlated (`rho <= -0.40` default) candidates, and (2) three bounded [-1,1] per-asset
"polarity" metrics (`zscore_tanh`, `percentile_rank`, and `eg_spread_zscore` — all three built for
comparison per Ross's request, not just one) whose rolling anti-correlation with each other is the
literal "opposite extremes" signal.

**Verified first** (`debug/_verify_inverse_polarity.py`, 8/8 pass): all three polarity metrics
correctly bounded to [-1,1] and recover known extremes; `polarity_anti_correlation` correctly reads
near -1 for a constructed true-opposite pair and near 0 for an independent pair; the cointegration
guard correctly ACCEPTS a genuine synthetic negative-hedge stationary spread (p=4e-8, hedge=-1.48)
and correctly REJECTS a synthetic spurious-correlation pair with no real equilibrium (Granger-Newbold
1974 style: correlated innovations, independent random walks — rho=-0.587, coint p=0.234, correctly
fails to reject the unit-root null); causality confirmed (no future leakage) for all metrics.

**A genuinely useful near-miss during verification, worth recording**: an earlier draft of the
"reject spurious correlation" test used two series with opposite constant DRIFT, expecting that to
produce negative return correlation with no cointegration. It didn't — rho came back ~0.03, not
negative at all, because Pearson correlation is computed on DEMEANED returns, and a constant drift is
entirely removed by demeaning. This is a real, useful methodological point for the module's own
premise: pure trend-divergence (the "drifts apart forever" failure mode) does not even register as
return anti-correlation in the first place — the raw-correlation stage already filters out that
specific pathology before cointegration is ever tested. The actual spurious-correlation risk this
module has to guard against is genuinely SYNCHRONIZED opposite-direction moves without a shared
error-correction term (correlated innovations, independent accumulation) — which the rebuilt test
now exercises correctly.

**Real-data run: honest null.** Screened against the 3 currently-confirmed pairs (`analysis.py`'s
2026-08-03 corrected re-run) — all three are POSITIVELY correlated (`IQV/Q` @1D rho=0.19, `KVUE/KMB`
@3m rho=0.43, `PNC/ZION` @4h rho=0.81), none anti-correlated. Unsurprising: the existing EG screen
tends to surface same-sector pairs (both banks, both consumer staples), which move together, not
oppositely — there is no reason to expect the *already-confirmed* set to contain "polar opposite"
candidates. Finding one requires scanning the full universe correlation matrix (all ~1660 assets,
not just the 3 already-confirmed pairs) — a materially heavier job than what ran here, deliberately
not launched without Ross's go-ahead given the compute cost.

**Real integration bug found and fixed while running on real data** (not caught by synthetic
verification, since synthetic pairs are constructed with matching lengths by hand): `IQV/Q`'s aligned
frames came back as `(3297, 7)` vs `(161, 7)` — `aligned_pair_loader.align_pair_dataframes` does not
guarantee identical df_a/df_b length (Q's cache only starts 2025-10-27, a recent listing). This is a
previously-documented gotcha (`research/bounded_lookback_primary_screen.py` hit the same class of bug
live on AME/MAR@1h) — fixed with the same established pattern, `df_a.index.intersection(df_b.index)`
before building arrays.

**Full-universe scan, run 2026-08-03 (`--full-universe` mode, added same day)**: 1730 symbols with
cached 1D data, 1705 aligned, 1697 survive `min_overlap=252`, full 1697×1697 correlation matrix
(1,439,056 pairs) computed via `analysis.py`'s own `DataAligner.align_universe` /
`UniverseFilter.build_returns_matrix` / `UniverseFilter.correlation_matrix` — reused directly, not
reimplemented. Result: only **2 pairs** anywhere in the full universe clear `rho <= -0.40`
(`ADT/BIVV` rho=-0.440, `BIVV/SANM` rho=-0.475) — confirming how rare strong anti-correlation actually
is across 1730 real assets, not an artifact of a small candidate set. **Neither is actually
cointegrated**: `coint_pvalue` = 0.8710 and 0.4054, both far above any reasonable significance bar —
this is precisely the "correlated but no real equilibrium" failure mode the module's two-stage screen
exists to catch, and it caught it correctly on real data.

**A real reporting bug found and fixed at this scale, not caught by synthetic verification (a pure
labeling bug, not a computational one)**: the original real-data print labeled both candidates
`[NEGATIVE-HEDGE COINTEGRATED]` based only on the fitted hedge ratio's SIGN
(`result["is_negative_hedge"]`), never checking `coint_pvalue` — so a correlated-but-not-cointegrated
pair was being reported as if it were a confirmed finding. Fixed: the label now requires both a
negative hedge AND `coint_pvalue < 0.05`; re-verified against the two real observed values (correctly
now labeled "correlated but NOT cointegrated") plus a synthetic p=0.001 control case (correctly still
labeled cointegated). **Bottom line, honestly stated**: across the entire real universe this project
tracks, zero genuine "polar opposite" equilibrium pairs currently exist. A real, informative null —
not a placeholder for "we haven't looked yet."

Files: `research/inverse_polarity.py` (new), `debug/_verify_inverse_polarity.py` (new, 8/8 pass),
`output/research/inverse_polarity_screen.parquet` (3 rows, 0 candidates),
`output/research/inverse_polarity_full_universe.parquet` (2 rows, 0 confirmed).

## 19. Trig-Identity Convergence/Divergence Comparison Arm — A Design Error Caught by Verification,
Then a Corrected Honest Null [2026-08-03]

Ross's framing: map a bounded metric CAMARF already tracks onto trig identities to look for
convergence/divergence, and/or produce a graphed (phase-portrait-style) relationship. Built as
`research/trig_convergence.py`, standalone (not folded into `inverse_polarity.py`, per Ross's
explicit choice), comparing two angle mappings (`arccos`, `arcsin`) applied to the bounded polarity
scores from Finding #18.

**Where this actually sits relative to existing machinery, stated plainly rather than oversold**:
Pearson correlation is already `cos(θ)` between two demeaned return vectors — every correlation
matrix `analysis.py` has ever produced already *is* a matrix of cosines. `cycle_detection.py`'s
rolling PLV is already the trig-identity form of phase sync (`|mean(cos Δφ) + i·mean(sin Δφ)|`). This
module does not add either of those. What's actually new: mapping the bounded `[-1,1]` polarity
scores onto an angle (`arccos`/`arcsin`, both built and compared per Ross's request), then a
sum-to-product decomposition of the polarity difference into a co-movement factor (half-sum) and a
divergence factor (half-difference) — exact algebraic identities, verified to reconstruct the
original polarity difference to floating-point precision (`debug/_verify_trig_convergence.py`, max
error ~1e-16).

**A real design error, caught by synthetic verification before touching real data — documented per
CLAUDE.md rule 8 rather than silently fixed.** The first draft claimed a true polar-opposite pair
(`p_B = -p_A` always) produces `θ_A - θ_B` stationary near `±π` under both mappings, and proposed
trading *drift in that difference* as the break signal. The synthetic test failed immediately
(`mean|θ_A-θ_B| = 1.159`, not `π`). Root cause, confirmed algebraically: `arccos(-x) = π - arccos(x)`
and `arcsin(-x) = -arcsin(x)`, so for a perfect opposite pair `θ_A - θ_B = 2θ_A - π` (arccos) or
`2θ_A` (arcsin) — **not constant**, it swings across the full range as the pair cycles. What actually
is constant, exactly, regardless of cycle position: the **sum** `θ_A + θ_B = π` (arccos) or `= 0`
(arcsin). Corrected design: the real polar-opposite invariant is the co-movement factor (built from
the half-sum), and the break/health signal (`opposite_equilibrium_break_signal`) tracks *that term's*
drift from its theoretical constant, not the divergence term's. Re-verified against the corrected
hypothesis (`debug/_verify_trig_convergence.py`, 6/6 pass after the numerical-stability fix below): `θ_A+θ_B` exactly constant to `4e-16` for
a true opposite pair across a full oscillating cycle (not just at the `±1` extremes); the original
wrong hypothesis explicitly re-checked and confirmed false (`θ_A-θ_B` range `3.75`, not near zero);
causality confirmed; the break signal correctly spikes at a constructed genuine equilibrium collapse
and not before.

**Real-data run, honest null, consistent with Finding #18**: run against the same 3 confirmed pairs,
none of which are anti-correlated. Deviation from the polar-opposite invariant scales with how far
from anti-correlated each pair actually is — `KVUE/KMB` (weakest correlation, ρ=0.43) shows the
smallest deviation (0.33–0.52), `PNC/ZION` (strongest, ρ=0.81) the largest (1.43–1.64) — a sensible
real-data consistency check, not formally part of the synthetic suite.

**Ross asked whether the divergence between `arccos` and `arcsin` was statistically significant —
investigated directly rather than run a formal significance test, since the algebra already answers
it.** Proved computationally, not just asserted: `co_movement` is bit-identical between mappings
(`arccos(p) = π/2 - arcsin(p)` is an identity; verified diff ~5e-16, machine precision), and
`divergence` is an exact sign-flip (`divergence_arccos = -divergence_arcsin`, verified diff ~2e-16).
The two mappings carry **zero independent information relative to each other** in this decomposition
— `arcsin`'s output is a fully deterministic function of `arccos`'s. A formal significance test would
have been testing whether floating-point noise is significant, not an economic question — a stronger
and more useful answer than a p-value would have given.

**A real bug did surface from asking the question, though — not a phantom.** The first real-data run
showed `mean_break_signal_abs_z` genuinely differing between mappings on some pairs (`KVUE/KMB`:
0.522 vs 0.476) despite the two `co_movement` series being mathematically identical. Traced to the
rolling-std denominator in `opposite_equilibrium_break_signal`: in the exact regime this module cares
about most — `co_movement` pinned near-constant, i.e. a genuine polar-opposite pair — the true
variance is at or below float64 noise, so the ~5e-16 rounding difference between mappings tips the
computed std to opposite sides of exactly zero, producing a different NaN pattern per mapping (12,343
vs 13,536 finite bars on the same underlying series) and therefore a different aggregate mean. Fixed
with a documented `_MIN_STD_FLOOR = 1e-6` clip (`debug/_verify_trig_convergence.py`, new check 5/6,
confirms both mappings agree bar-for-bar in a synthetic pinned-regime case after the fix). Re-run
against real data: every one of the 12 rows now matches **exactly** between `arccos` and `arcsin`,
confirming the algebra held all along and the discrepancy was purely a numerical-stability bug in the
signal computation, not a property of the underlying quantity.

Same conclusion as Finding #18 follows: like the polarity screen, this needs the full-universe
correlation matrix (not just the 3 already-confirmed, positively-correlated pairs) to find anything —
not launched without Ross's go-ahead given the compute cost. The graphed-relationship half of Ross's
original request (a phase-portrait / polar-plot visualization of `θ_A` vs `θ_B` over time) is not yet
built — flagged here so it isn't silently dropped, not done in this entry.

Files: `research/trig_convergence.py` (new), `debug/_verify_trig_convergence.py` (new, 6/6 pass),
`output/research/trig_convergence.parquet` (12 rows: 3 pairs × 2 metrics × 2 mappings).

## 20. Parameter Sensitivity for the Session 30 Comparison Arms — Batch 1 of a Multi-Session Effort
[2026-08-03]

Ross asked to extend `sensitivity.py`'s existing parameter-grid-vs-headline-metric pattern to the
`research/*.py` comparison arms, confirmed as a **bespoke, per-script** effort (not a generic
mechanical sweep) — real multi-session work. Survey: 120 research scripts total, 46 with real
CLI-tunable numeric parameters, 74 fixed-logic diagnostics sensitivity doesn't apply to in the same
way. **Batch 1** (`research/sensitivity_research.py`, new): the 6 sweepable Session 30 arms (5 of the
7 built this session, plus `inverse_polarity`'s full-universe mode). `svm_gradient_descent_classifier`
excluded — it has no CLI parameters at all, and is currently data-blocked (19/30 examples per
Finding #17), not parameter-blocked, so a sweep would be meaningless right now. **The remaining 39
parameterized scripts are explicit backlog, not silently dropped** — each needs the same
headline-metric identification work this batch did, one script at a time.

Each script run as a subprocess across its own small grid (5 values, baseline included), headline
metric(s) extracted via regex from stdout (for scripts with clean scalar summaries) or read directly
from the script's own output parquet (for `trig_convergence`, whose headline is a table, not a scalar
print).

**Results, one per arm:**

- **`cycle_detection` (`--plv-window` ∈ [30,45,60,90,120])**: `mean_plv` stays in a tight, unremarkable
  band (0.43–0.51) throughout — Finding #13's honest null holds. **A real methodological catch,
  not previously visible**: `n_pairs_reported` drops from 3 to 2 once `--plv-window >= 60` — the
  module's own minimum-bars gate scales as `3× plv_window`, so one (pair, TF) combination silently
  falls out of the sample at larger windows, changing what's actually being averaged without any
  error or warning. Worth disclosing in any future use of this module at non-default windows.
- **`levy_jump_diffusion` (`--alpha` ∈ [0.001,0.005,0.01,0.05,0.10])**: `mean_gapflag_overlap_pct`
  stays at **exactly 0.0** across the entire grid — Finding #14's headline claim (jumps and GapFlag
  detect unrelated things) is robust to the significance threshold, not a default-alpha artifact.
  `jump_frac` rises monotonically with looser alpha (2.43%→3.34%), the expected mechanical effect of
  a looser bar, not a fragility.
- **`rough_volatility` (`--rv-window` ∈ [15,20,30,45,60])**: a real, non-trivial finding — `H_rs`
  crosses **above 0.5** (the not-rough side) once the window reaches ~45–60 (0.42→0.51), while
  `H_dfa`/`H_wavelet` stay well below 0.5 throughout (0.16–0.43). Finding #15's "mixed signal,
  estimators disagree" is not just present, it's **window-dependent** — the disagreement sharpens at
  larger windows rather than staying constant. Worth investigating further before treating any single
  window's roughness estimate as authoritative.
- **`options_greeks_features` (`--window` ∈ [15,20,30,45,60])**: statistical significance
  (`p=0.0`) holds at every window, but effect size decays substantially — `r` falls from 0.44 (windows
  15–30) to 0.15 (window 60), roughly a 3× drop. Consistent with Finding #16's "likely a price-level
  confound" read: a genuine structural relationship would be expected to hold its magnitude better
  across window choices than a confound whose influence dilutes as the window lengthens.
- **`inverse_polarity` full-universe (`--corr-threshold` ∈ [-0.30,-0.35,-0.40,-0.50,-0.60])**: the
  strongest result of the batch. Even loosening the threshold to -0.30 (20 raw candidates, 10× more
  than at the -0.40 baseline) finds **zero genuinely cointegrated pairs** — `n_genuinely_cointegrated
  = 0` at every single threshold tested. Finding #18's null ("no polar-opposite equilibrium currently
  exists in this universe") is not an artifact of one threshold choice — it holds across a wide,
  reasonable range, which is real evidence *for* the null, not just an absence of evidence against it.
- **`trig_convergence` (`--window` ∈ [30,45,60,90,120])**: stable throughout —
  `mean_sum_deviation` 0.89–1.00, `mean_break_signal_z` 0.63–0.81, no dramatic swings. Finding #19's
  honest null is not a single-window artifact.

**Harness bug found and fixed while assembling this entry, worth recording**: `--only` mode saved by
overwriting `research_scripts_sensitivity_batch1.parquet` from scratch each invocation, rather than
merging — running the 6 arms as 6 separate `--only` calls (done here to manage memory pressure from
concurrently-running background jobs, one arm at a time) silently discarded every earlier arm's rows,
leaving only the last-run arm on disk. Fixed to merge by `comparison_arm` (replace just the
re-run arm's rows, keep everything else) rather than blind overwrite. The full 30-row result below was
reconstructed from the actual verified run output already produced before the bug was caught, not
re-run from scratch (the full-universe sweep alone is too expensive to redo unnecessarily).

Files: `research/sensitivity_research.py` (new), `output/sensitivity/research_scripts_sensitivity_
batch1.parquet` (30 rows: 6 arms × 5 grid points each). No new `debug/_verify_*.py` — this batch runs
already-verified modules across parameter grids, it doesn't introduce new math needing its own
synthetic proof.

## 21. Parameter Sensitivity, Batch 2 — Six More Research Scripts, Prioritized by Centrality to Core
Methodology [2026-08-03]

Continuation of Finding #20's multi-session effort. Picked 6 of the remaining 40 parameterized
scripts for centrality to the project's core cointegration/lead-lag/robustness methodology — closest
to touching `PAPER.md`-level claims. **34 scripts remain after this batch** — still explicit backlog,
tracked in `Development.md`, not silently dropped.

**Results:**

- **`eg_permutation_check` (`--n-perm` ∈ [100,200,500,1000])**: `mean_null_frac_significant` drifts
  from 0.045 → 0.062 as permutation count increases — moving slightly AWAY from the textbook ~0.05
  expectation as the estimate gets less noisy, not converging toward it. A mild, real finding: the
  baseline `n_perm=500` reading (0.056) may understate a small excess false-positive risk that only
  becomes visible with more permutations. Not dramatic, but worth a note if this module's output is
  ever promoted beyond a diagnostic.
- **`tail_dependence` (`--asymmetry-threshold` ∈ [0.10,0.15,0.20,0.25])**: `gate_flagged=False` at
  every threshold in the range — the "no material tail asymmetry" null is robust, not a fragile
  boundary case sitting right at the default.
- **`variance_ratio_test` (`--q-values` ∈ [{2,4,8}, {2,4,8,16}, {4,8,16,32}])**: the directional
  finding (VR<1, mean-reversion) is **100% consistent** — `n_vr_below_1 == n_valid` in every single
  grid tested. Significance count softens at the longest-horizon grid (2→1 significant at p<0.05),
  worth noting given small n (5-6 valid tests) rather than treating as a contradiction. **Real bug
  found and fixed running this sweep**: the harness's output `value` column mixed float (other arms'
  numeric grids) and string (`"2 4 8"`, this arm's multi-value grid) types in the same column, which
  pyarrow refuses to write (`ArrowInvalid: Could not convert '2 4 8'...`). Fixed by storing `value` as
  string universally across all arms (parse back to float at read time for numeric-grid arms if
  needed) — applied retroactively to the already-saved batch 1 rows too.
- **`wavelet_hurst_comparison` (`--tf` ∈ [1h,4h,1D])**: stable, unremarkable divergence values
  (0.018–0.089) across all three timeframes — the RS/DFA/wavelet estimator-disagreement pattern
  replicates across TFs, not specific to the 1h default. A `--tf` sweep is this project's own
  established robustness-check convention (does a finding hold across timeframes), applied here
  rather than a generic parameter grid.
- **`threshold_cointegration` (`--n-boot` ∈ [100,250,500,1000])**: perfectly stable —
  `n_significant=0` at every single bootstrap-draw count. The baseline count wasn't noisy; the null
  (no significant threshold effects among the 2 tested pairs) is robust.
- **`regime_cluster_robustness_check` (`--n-boot` ∈ [50,100,200,400])**: `found_frac=0.0` at every
  `n_boot` — the bootstrap never once found the target cluster, at any draw count. Ironic given the
  script's own name, but a genuine, stable null, not a bug (0/n_boot consistently, not an
  intermittent or noisy zero).

Files: `research/sensitivity_research.py` (extended, not a new file — `BATCH2_REGISTRY` merged into
the same `REGISTRY`), `output/sensitivity/research_scripts_sensitivity_batch1.parquet` (52 rows: 12
arms total across both batches — filename kept as-is despite now covering 2 batches, to avoid
doc/file mismatches across Findings #20/#21; the merge-by-`comparison_arm` logic in the harness
already handles accumulating across batches correctly regardless of the filename).

## 22. Intraday Episodic Window/Step Sizing — an Actual Test, not a Guessed Constant [2026-08-08]

Directly answers Ross's request: *"we should change the 200 bars and run an actual test to see what
value makes a valid relationship... that goes for any and all hardcoded values."* The "200 bars" is
`structural_break_onset_detection.py`'s `MIN_SEGMENT_BARS=200`, already diagnosed as producing 9
spurious "breaks" on `KVUE/KMB@3m` in a couple months (200 bars at 3m granularity is only a few
days, not real regime-change timescale). Rather than pick a new number, this builds a new intraday
episodic scanner's window/step choice from 4 candidate configs, each derived from an existing
production convention, and evaluates them on real data with two metrics stated before running, not
chosen post-hoc.

**First, a real prerequisite finding**: is enough intraday history available to even ask this
question at scale, or is it a `PNC/ZION`-only situation? Checked directly
(`debug/_check_intraday_cache_coverage.py`, new): of 1,576 cached `*_1hr.parquet` symbols, **1,535
(97%) have >= 2 years of history** (median ~1,103 days ≈ 3yr); `*_4hr.parquet` is essentially
identical (1,573 symbols, 1,531 ≥ 2yr). **Universe-wide, not a special case.**

**The 4 configs tested** (`research/intraday_episodic_window_sensitivity.py`, new, verified 9/9
synthetic checks first — one real bug caught: `onset_anchored` was silently dropping every window
anchored near the end of available data, fixed to clip-not-drop, mirroring `find_all_breaks`'s own
pattern): `fixed_min_overlap_1x`/`_2x` (1x/2x `Config.STATS.MIN_OVERLAP_BY_TF[tf]`),
`adaptive_halflife_8x` (per-pair, via `SpreadModel._adaptive_window`, the same half-life-relative
convention already used in production z-score estimation), `onset_anchored` (window start at
`structural_break_onset_detection.py`'s detected onset date).

**Real result, on real PNC/ZION + KVUE/KMB + IQV/Q 1h data:**

| config | n_confirmed | perturbation counts | CV (stability) | PNC/ZION windows | PNC/ZION contiguity |
|---|---|---|---|---|---|
| fixed_min_overlap_1x | 1 | [1,2,2] | 0.283 | 20 | 0.857 |
| fixed_min_overlap_2x | 1 | [1,1,1] | **0.000** | 8 | **1.000** |
| adaptive_halflife_8x | 1 | [1,1,1] | **0.000** | 20 | 0.857 |
| onset_anchored | 2 | [2,1,2] | 0.283 | 5 | **1.000** |

Two configs (`fixed_min_overlap_2x`, `adaptive_halflife_8x`) show perfect confirmed-count stability
across window perturbations (CV=0.0); `adaptive_halflife_8x` gets there while testing 2.5x more
windows for PNC/ZION at the same contiguity as `fixed_min_overlap_1x`. `onset_anchored` found one
additional confirmed pair but is the least stable and has the fewest PNC/ZION windows to judge from.
**No winner is declared here** — the new intraday episodic scanner (`research/intraday_episodic_
scan.py`) defaults to `fixed_min_overlap_2x` (the empirically most stable, and the only kind of
config the scanner's batched-pooling machinery can use as a single global window/step — `adaptive_
halflife_8x`/`onset_anchored` are inherently per-pair, disclosed as a scope limit in that script's
own docstring rather than force-fit), with `--window-config` exposed to try `fixed_min_overlap_1x`
too. Which config should ultimately govern production is Ross's call, once the fuller comparison
(episodic scan real output, not yet complete as of this writing) exists to judge against.

Files: `research/intraday_episodic_window_sensitivity.py` (new), `debug/_verify_intraday_episodic_
window_sensitivity.py` (new, 9/9 pass), `debug/_check_intraday_cache_coverage.py` (new),
`output/research/intraday_episodic_window_sensitivity.parquet` (new, real run),
`output/research/intraday_cache_coverage.parquet` (new, real run).

## 23. Episodic Confirmation's Duration/Degree Knobs — Precision Rises With Strictness, Recall
Collapses, No Overfitting Signal [2026-08-09]

Directly answers Ross's request: *"run the test for at what length of time and degree of
cointegration is it actually accurate and usable for us."* Distinct from Finding #22 (which tuned
the intraday scanner's rolling-WINDOW width) — this tunes the episodic screen's own two
confirmation knobs, **duration** (`min_windows_confirmed`) and **degree** (`alpha`), against real
forward usability rather than in-sample statistical significance alone.

**A real methodological correction made before trusting any result, worth recording as process, not
just outcome**: the first version of this test scored grid cells on raw accuracy and got a
suspiciously flat ~91-92% across every one of 12 cells. Checked directly rather than assumed fine:
ground truth ("did the pair's cointegration actually hold up in a later, held-out period") is only
**8.3% positive** (16,819/202,257 candidate pairs) — a trivial "always predict not-confirmed"
baseline already scores ~91.7% by matching the majority class, which is almost exactly what was
observed. Accuracy was the wrong metric entirely at this class balance. Replaced with **precision**
(of the pairs a given duration/degree threshold would confirm, what fraction actually held up
forward — the directly decision-relevant question for "should I trust this confirmation") and
**recall**, reported honestly alongside so a cell can't look good purely by confirming almost
nothing.

**Real result** (`research/episodic_duration_degree_usability.py`, verified 12/12 synthetic checks
first, real run against the existing WRDS/1D episodic scan's 202,257 candidate pairs — no new scan
needed, this reused already-on-disk `wrds_deep_history_episodic_scan_tier{2,3}_windows.parquet`):

| min_windows_confirmed | alpha | precision | recall | n_confirmed |
|---|---|---|---|---|
| 1 | 0.01 | 0.215 | 0.0027 | 209 |
| 1 | 0.05 | 0.205 | 0.0082 | 673 |
| 1 | 0.10 | 0.210 | 0.0174 | 1,394 |
| 2 | 0.10 | 0.251 | 0.0064 | 431 |
| 3 | 0.05 | 0.467 | 0.0004 | 15 |
| **3** | **0.10** | **0.382** | **0.0015** | **68** |
| 5 | 0.10 | 0.600 | 0.0004 | 10 |

Precision rises meaningfully with stricter duration/degree requirements (0.21 at the loosest
setting → up to 0.60 at the strictest), roughly **2.5x-7x the 8.3% unconditional base rate** — a
real, usable signal, not noise. But recall collapses just as fast (1.7% down to 0.04%), and the
strictest cells confirm too few pairs to trust their own precision estimate (`min_windows_
confirmed=5, alpha=0.01` confirms **zero** pairs at all — precision is mathematically undefined
there, not a real 0 or 1, and this project's own harness now refuses to silently treat an
undefined precision as a winning cell, requiring >=20 confirmed pairs for eligibility).

**Recommended cell, among those confirming enough pairs to trust the estimate**:
`min_windows_confirmed=3, alpha=0.10` — precision 0.382. **Required overfitting guard** (same
discipline as `coint_frac_window_grid.py`): pairs split into two disjoint halves, this cell selected
on half A (precision 0.381), scored on untouched half B (precision **0.4375**) — held-out precision
was actually *higher* than in-sample, the opposite direction overfitting would produce. No
overfitting signal at this setting.

**Honest scope note**: this result is scoped to the WRDS/1D episodic source only (real data,
available now); it should be re-run once the intraday (1h/4h) episodic scan (Step 2 of the current
master plan) completes, since duration/degree tradeoffs could plausibly differ at intraday
granularity where "a window" spans much less calendar time. Whether `min_windows_confirmed=3,
alpha=0.10` (or any specific cell) should become a new production default, versus staying a
research-only diagnostic, is Ross's decision from these numbers — not decided here, consistent with
this project's comparison-arm-before-promotion discipline.

Files: `research/episodic_duration_degree_usability.py` (new), `debug/_verify_episodic_duration_
degree_usability.py` (new, 12/12 pass), `output/research/episodic_duration_degree_usability.parquet`
(new, real run).

**SUPERSEDED-BUT-CONFIRMED update (2026-08-12, after BUG-D112's fix)**: the table above was
computed against the candidate-generation-lookahead-contaminated WRDS/1D scan (see BUG-D112,
`docs/BUG_LOG.md`). Re-ran the identical script against the fixed, causally-gated Tier 3 scan
output once the redo completed. The recommended cell's basic shape holds: `min_windows_confirmed=3,
alpha=0.10` remains the strictest cell with enough confirmed pairs to trust (44 confirmed, of
118,575 total scored candidate windows — both numbers differ from the original 68/202,257 since the
fixed candidate pool is smaller and causally gated), precision **0.4545** (up slightly from the
original contaminated run's 0.382), and the overfitting guard again shows **no overfitting** — half-A
selected precision 0.4545 (`(3, 0.1)` is again the best cell on half A), held-out half-B precision
**0.4783** (higher than in-sample, gap -0.0497). The full grid (12 cells: `min_windows_confirmed` in
{1,2,3,5} x `alpha` in {0.01,0.05,0.10}) is unchanged in shape — precision still rises with
stricter duration/degree settings, recall still collapses, `min_windows_confirmed=5, alpha=0.01`
still confirms zero pairs (undefined precision). **Conclusion: Finding #23's methodology and
recommended cell survive the BUG-D112 fix intact** — the original directional finding (stricter
duration/degree confirmation buys real, non-noise precision at a steep recall cost) was not an
artifact of the candidate-generation contamination, just computed against a mildly larger,
pre-fix candidate pool. Real re-run output: `output/research/episodic_duration_degree_usability.parquet`
(overwritten in place, 2026-08-12; the pre-fix table above is preserved here in this file, not
deleted, per this project's "document what was tried" rule).

## 24. BUG-D112 Redo — Real Step 5 Portfolio Backtest Results Supersede the Provisional 454-Pair
Numbers [2026-08-12]

Supersedes the provisional Step 5 comparison in the disclosure section below (which was run
against the 454-pair set later found contaminated by BUG-D112's candidate-generation lookahead
bias — see `docs/BUG_LOG.md`). After the fix (Tier 2 excluded from PIT-safe sources; Tier 3 gated
so a pair is only EG-tested on windows dated at or after when it would genuinely have qualified as
a candidate), the full redo sequence — re-scan, adapter rebuild (with a second real bug found and
fixed along the way: the adapter's resume-checkpoint logic was reintroducing stale, no-longer-
confirmed pairs; see BUG-D112's bug-log entry), comparison-arm rebuild, `ml.py --pit-safe` retrain,
Step 5 re-run — produced these real, non-provisional numbers:

- **Real PIT-safe universe: 182 pairs** (170 WRDS/1D, 6 intraday/1h, 6 intraday/4h) — down from the
  contaminated run's 454, as expected once candidate-generation is properly causally gated.
- **`ml.py --pit-safe` retrain**: test_accuracy **52.58%** (n_train=7544, n_test=2516), conformal
  coverage **91.26%** (n_cal=2514, avg_set_size=1.77) — up from the provisional 52.94%/87.85%.
  4 pairs skipped for zero labeled entry events (`KEY/RF@4h`, `CMS/PPL@4h`, `SPY/VOO@4h`,
  `CFG/COLB@4h`).
- **Step 5 portfolio backtest** (`--capital-sim`, $100k fixed sizing), real numbers:

| Arm      | IS Sharpe | OOS Sharpe |
|----------|-----------|------------|
| Purity   | -0.679    | -0.834     |
| Hybrid   | -0.442    | -1.125     |
| Tiered   | +1.417    | +0.630     |
| Baseline | +1.417    | +0.630     |

**Headline, honest finding**: the genuinely PIT-safe 182-pair Purity universe loses money under
realistic capital-constrained sizing, both in-sample and out-of-sample — a real result, not an
artifact of the fixed bug (if anything, the contaminated 454-pair run's Purity Sharpe of -0.95 was
already directionally the same conclusion; the fix changes the magnitude and the honest provenance
of the number, not the qualitative finding that PIT-safe pairs currently don't produce a positive
realistic-capital edge). Hybrid (mixes in the 3 non-PIT-safe standard pairs) is similarly negative
on both IS and OOS, actually worse OOS than Purity alone. Tiered and Baseline post identical
positive numbers (+1.417 IS / +0.630 OOS) — **this is a capital-efficiency artifact, not evidence
that PIT-confidence tier-weighting adds value**: at this snapshot all 3 non-PIT-safe standard pairs
(the ones actually driving the positive Sharpe) share one uniform PIT-confidence tier weight, so
Tiered's weighting scheme has nothing to differentiate — it degenerates to the same trade set and
sizing as Baseline. Tier-weighting's real effect can only be tested once the PIT-safe universe
itself contains pairs spanning multiple genuine confidence tiers, which it currently does not
(all 182 pairs come from the same episodic-confirmation methodology, not a mix of tiers).

Files: `research/episodic_pairs_adapter.py` (stale-checkpoint fix), `debug/_verify_adapter_stale_
checkpoint_fix.py` (new, verified before the real rebuild), `output/research/step5_arm_results/
real_*` (new, real numbers — `provisional_pre_bugd112/` holds the old contaminated-run files,
preserved not deleted).

## 25. Thread G Phase 1 — OAT Parameter Sensitivity Screen: Entry Threshold Dominates, Kelly Sizing
Untestable at This Universe's Trade Volume [2026-08-12]

First real answer to Ross's "every factor must be scrutinized" directive. Phase 1 (one-at-a-time
screening, wide net) swept 3 backtest.py-level design parameters against the real, BUG-D112-fixed
182-pair Purity universe, `--capital-sim` ($100k), both IS and OOS, with an overfitting guard (does
the IS-best grid value also look good OOS, same "select on one half, verify on the other"
discipline as Finding #23): `ENTRY_ZSCORE` (`--entry-z`, grid 1.5/2.0/2.5/3.0), hedge method
(`--hedge`, both/ols/kalman), and capital-sizing method (`--capital-sizing`, fixed/equity_
proportional/quarter_kelly/third_kelly/half_kelly/full_kelly). Explicitly NOT covered this pass —
tracked, not dropped: `--risk-parity`/`--hrp-weight`/`--pit-confidence-weight` (each has a real
IS-fitting state dependency on `trades_layer1.parquet`, per BUG-D76, needing careful sequencing
before a clean sweep is possible) and every episodic-confirmation-level parameter (`min_windows_
confirmed`, `alpha`, `tier3_threshold`, window/step sizes, the ~90-day fundamentals reporting lag)
— each requires a multi-hour re-scan per grid point, not a cheap CLI sweep.

**Effect size ranking** (range of `sharpe_portfolio` across the grid — the bigger the range, the
more this parameter actually moves the result):

| param | split | sharpe_range | sharpe_min | sharpe_max |
|---|---|---|---|---|
| entry_zscore | IS | 1.182 | -1.036 | +0.146 |
| entry_zscore | OOS | 0.971 | -1.150 | -0.179 |
| hedge_method | OOS | 0.591 | -1.102 | -0.511 |
| capital_sizing_method | IS | 0.203 | -0.679 | -0.476 |
| hedge_method | IS | 0.078 | -0.746 | -0.668 |
| capital_sizing_method | OOS | 0.007 | -0.834 | -0.827 |

**Entry threshold (`ENTRY_ZSCORE`) is by far the strongest real lever found so far** — both the
largest IS and second-largest OOS effect size. `z=3.0` is the IS-best AND the OOS-best value (no
overfitting risk: IS-best's OOS rank is 1/4), the only cell in this entire screen with a positive
IS Sharpe (+0.146), and its OOS Sharpe (-0.179) is dramatically better than the current default
`z=2.0`'s OOS Sharpe (-0.834) — an honest, real, non-noise, non-overfit signal that the current
default entry threshold may be too loose for this specific 182-pair PIT-safe universe. Not yet a
production recommendation (Phase 1 is a screen, not a promotion decision — same discipline as this
project's comparison-arm-before-production rule), but the strongest single finding this screen
produced.

**Hedge method: OLS beats the default "both" pool and Kalman, consistently** — smaller effect than
entry-z but real and non-overfit (OLS is IS-best AND OOS-best, rank 1/3 both times). Pooling
OLS+Kalman trades together (`--hedge both`, the project's own default) is worse than OLS alone on
both splits — a real, if modest, signal that Kalman-hedged trades are diluting rather than helping
in this universe.

**Capital-sizing method: a genuine scope limitation, not a null result on Kelly sizing itself** —
investigated directly rather than reported at face value, since all 4 Kelly variants (quarter/
third/half/full) produced BIT-FOR-BIT IDENTICAL output (IS: 11 trades taken, Sharpe -0.4757; OOS: 7
trades, Sharpe -0.8323), which would be a red flag if left unexplained. Root-caused in `portfolio_
sim.py`: `_kelly_fraction()` requires `_KELLY_MIN_TRADES = 60` closed trades before it estimates a
real Kelly fraction (`f_star`); below that it always falls back to the same `flat_2pct` risk
sizing regardless of which Kelly multiplier (0.25/0.333/0.5/1.0) was requested. This Purity
universe's risk-based sizing methods (`flat_2pct` and the Kelly family, which both require a
causally-estimable `risk_per_share` via `stop_distance_dollars_per_share`) take far fewer trades
than `fixed`/`equity_proportional` (11-149 vs 105-149) and never accumulate the 60 closed trades
needed for Kelly's fraction estimate to ever activate — so the Kelly-fraction PARAMETER is
currently untestable at this universe's trade volume, not evidence it doesn't matter. This is a
real, useful negative finding in its own right (a design parameter this project built and never
sensitivity-tested turns out to have zero possible signal at current trade counts) and flags a
separate, genuine question worth its own follow-up: does risk-based sizing's much smaller trade
count (vs. fixed sizing) reflect a real risk-estimation constraint, or an overly conservative skip
condition in `stop_distance_dollars_per_share`/`_kelly_fraction`'s NaN-fallback path — not answered
here, noted as a candidate for a future targeted investigation, not Phase 1's scope.

**Overfitting guard result, all 3 parameters**: no overfitting risk flagged for any of the 3 —
every IS-best value's OOS rank was in the top half of its grid (entry_zscore 1/4, hedge_method
1/3, capital_sizing_method 2/6). The capital_sizing_method "no overfitting" result should be read
with the scope-limitation caveat above in mind (the whole Kelly family is a flat tie under the
fallback, so "IS-best" there is really "IS-best among fixed/equity_proportional/degenerate-Kelly",
not a meaningful Kelly-specific comparison).

**Phase 2 (interaction study) is explicitly gated on Ross's review of these survivors** — not
started automatically, per the master plan's own "a real decision point, not automatic" design.
`entry_zscore` is the clear, strong candidate; `hedge_method` a real but modest one; `capital_
sizing_method` needs either a larger-trade-count universe or the sizing-mechanism follow-up above
before it can be meaningfully screened at all.

Files: `research/parameter_sensitivity_screen.py` (new), `output/research/param_sensitivity/
phase1_oat_results.parquet`, `phase1_overfitting_guard.parquet`, `phase1_effect_size_ranking.parquet`
(new, real runs — 26 real `backtest.py --capital-sim` subprocess invocations, individual portfolio/
trades outputs archived per grid point).

## 26. Kelly Sizing Root Cause + Entry Z-Band Comparison Arm — the Entry-Overflow Gap Is Real But NOT
the Dominant Blocker [2026-08-12]

Ross asked why the 4 Kelly variants in Finding #25 tied exactly. Investigated directly against the
real 32,793-candidate Purity IS trade list rather than accepting the scope-limitation explanation
at face value.

**Root cause, confirmed with real sampled data**: `stop_distance_dollars_per_share()` returns NaN
whenever `|entry_z| >= STOP_ZSCORE (3.5)` at entry — a real, structural property of `backtest.py`'s
entry logic, which has **no upper z-bound** (entry only requires `|z| >= ENTRY_ZSCORE`, nothing
caps it above). A random 2,000-trade cross-section of the real trade list showed **56% of all
candidate entries already have `|entry_z| >= 3.5`** (consistent with the raw column stats: 25th/75th
percentiles are -3.59/+3.58, straddling the stop level on both sides) — any risk-based sizing
method (`flat_2pct` or Kelly) skips these outright. Of the remaining ~44%, median `risk_per_share`
is a tiny $0.135/share, which at 2% fixed risk on $100k equity implies a position size that
overshoots the account by 10-100x for many trades, tripping the 0.05 `size_scale` skip floor.
Combined: only 11/32,793 trades survive under `flat_2pct`/Kelly (IS) vs. 146/32,793 under `fixed`
sizing (no risk estimate needed). Kelly's own `f*` estimator additionally needs 60 closed trades
before activating (`_KELLY_MIN_TRADES`) — never reached here — so every Kelly multiplier silently
falls back to `flat_2pct`, explaining Finding #25's exact tie.

**New comparison arm built and tested to address the entry-overflow half of this**: added
`Config.BACKTEST.ENTRY_ZSCORE_MAX` (`config.py`, default `None` = unchanged behavior) and
`--entry-z-max` to `backtest.py`, gating entry to `ENTRY_ZSCORE <= |z| <= ENTRY_ZSCORE_MAX`
instead of unbounded above. Verified with a real-data sanity check before trusting it (a razor-thin
band `[2.00, 2.05]` on the 1D subset produced 11,010 trades vs. 32,200 unbounded — confirms the
gate is genuinely filtering, not a no-op) before running the real comparison.

**Real result, entry-z-max=3.5 (bounding at STOP_ZSCORE, the natural choice) vs. baseline
(unbounded)**:

| sizing | split | baseline sharpe | z-band[2,3.5] sharpe | baseline n_taken | z-band n_taken |
|---|---|---|---|---|---|
| fixed | IS | -0.679 | **-0.839** (worse) | 146 | 47 |
| fixed | OOS | -0.834 | **-0.657** (better) | 105 | 40 |
| flat_2pct | IS | -0.476 | **-0.644** (worse) | 11 | 13 |
| flat_2pct | OOS | -0.832 | -0.870 (worse) | 7 | 7 |

**Two honest, non-obvious conclusions, neither is what the initial hypothesis predicted**:
1. **Z-banding at 3.5 does NOT reliably improve Sharpe** — mixed IS/OOS results for `fixed`
   sizing, and worse on both splits for `flat_2pct`. This is meaningfully worse than Phase 1's
   `entry_z=3.0` (raising the FLOOR, no upper bound), which remains the strongest lever found
   (IS +0.146, OOS -0.179) — bounding entries and raising the entry floor are NOT the same lever,
   and the floor-raise alone outperforms the band tested here.
2. **The entry-overflow gap is real but is NOT the dominant blocker for Kelly viability.**
   Removing it (z-band[2,3.5]) barely moved `flat_2pct`'s trade count (11 -> 13 trades) and made
   its Sharpe worse, not better — most trades were already being skipped by the capital
   size-floor (tiny `risk_per_share` implying oversized positions), a mechanism the entry-overflow
   fix doesn't touch at all. Kelly/risk-based sizing's real blocker is the risk_per_share/available-
   capital mismatch, not the missing upper z-bound — a more precise, corrected diagnosis than the
   entry z-bound framing this investigation started with.

Files: `config.py` (`ENTRY_ZSCORE_MAX`, new), `backtest.py` (`--entry-z-max` flag, entry gate,
label suffix), `output/research/param_sensitivity/zband/*.parquet` (new, real runs).

## 27. Thread G Phase 2 — Entry-Z x Hedge-Method Interaction: a Real Interaction Exists, and the
Naive Combination of Two Good Marginal Choices Is NOT the Best Joint Choice [2026-08-12]

Full 4x3 reduced factorial (`entry_zscore` in {1.5, 2.0, 2.5, 3.0} x `hedge_method` in {both, ols,
kalman}), IS + OOS, against the real 182-pair Purity universe — the interaction study Phase 1
explicitly deferred pending Ross's review of survivors.

**IS pivot** (rows=entry_z, cols=hedge, values=sharpe_portfolio):

| entry_z | both | kalman | ols |
|---|---|---|---|
| 1.5 | -1.036 | -0.897 | -0.592 |
| 2.0 | -0.679 | -0.746 | -0.668 |
| 2.5 | -0.912 | -0.992 | -0.961 |
| **3.0** | **0.146** | **0.159** | **0.117** |

**OOS pivot:**

| entry_z | both | kalman | ols |
|---|---|---|---|
| 1.5 | -0.216 | -0.313 | -1.007 |
| 2.0 | -0.834 | -1.102 | -0.511 |
| 2.5 | -1.150 | -0.861 | -0.475 |
| **3.0** | **-0.179** | -0.748 | -0.610 |

**A real interaction exists, not just two independent marginal effects**: the best hedge method is
NOT consistent across entry_z levels, on either split (IS: ols/ols/both/kalman as entry_z rises;
OOS: both/ols/ols/both). Phase 1's own marginal finding ("OLS beats both/kalman") does not hold
at `entry_z=3.0` — the single most important entry_z level, where every hedge choice is positive
IS and best overall OOS.

**The naive combination of Phase 1's two "best" marginal choices (`entry_z=3.0` + `hedge=ols`) is
NOT the best joint cell — a concrete demonstration of why this project scoped Phase 2 at all,
not just Phase 1's OAT screen.** Two candidate cells at `entry_z=3.0`:
- `hedge=kalman`: the single BEST IS Sharpe in the entire 12-cell grid (+0.159) — but its OOS
  Sharpe (-0.748) is the WORST of the three hedge options at that entry_z level. Picking this cell
  from IS alone would have been a real overfitting trap.
- `hedge=both` (the project's own current default, NOT the Phase-1-recommended pure-OLS): the
  second-best IS Sharpe at `entry_z=3.0` (+0.146) AND the single BEST OOS Sharpe in the entire
  12-cell grid (-0.179) — no other cell, at any entry_z or hedge combination, beats it OOS.

**Recommendation, not yet acted on**: `entry_z=3.0` combined with the DEFAULT `hedge=both` (not a
switch to pure OLS) is the most robust cell found across all of Thread G — best OOS in the whole
grid, strong and non-overfit IS, and the entry_z=3.0 pattern holds regardless of hedge choice (all
3 hedge sub-cells positive IS at that level, a robust pattern, not a single-cell fluke). **Still an
honest, not-yet-profitable result**: OOS Sharpe -0.179 is the best found, not a positive number —
this is "the strongest lever Thread G has found so far," not "a fix that makes the PIT-safe
universe tradeable." Production promotion of `entry_z=3.0` (default hedge, unchanged) as the new
production default is a real, defensible candidate given this evidence, but remains Ross's decision
per this project's comparison-arm-before-production discipline — not promoted automatically here.

Files: `research/parameter_sensitivity_phase2_interaction.py` (new), `output/research/param_
sensitivity/phase2_interaction_results.parquet` (new, real run — 24 real `backtest.py --capital-sim`
invocations).

## Disclosure Added Retroactively to Findings #13–#19: All 7 Session 30 Comparison Arms Inherit the
Same Non-PIT Pair-Selection Bias Already Quantified in §7.3.1 [2026-08-03, flagged by Ross]

Ross pointed out mid-session that the project's pair universe is larger than the "standing" confirmed
set once episodic relationships are accounted for, and that **every research script must be
point-in-time (PIT) safe**. Checking this directly against the actual code (not assumed) confirmed a
real, previously-undisclosed gap: **all 7 comparison arms built this session
(`cycle_detection.py`, `levy_jump_diffusion.py`, `rough_volatility.py`, `options_greeks_features.py`,
`svm_gradient_descent_classifier.py`, `inverse_polarity.py`, `trig_convergence.py`) source their pairs
from the SAME non-PIT full-history screen** — `cycle_detection.py`/`inverse_polarity.py`/
`trig_convergence.py` call `ml._discover_confirmed_pairs()` directly (reads `output/results/*/
pairs.parquet`, produced by `analysis.py`'s full-history EG screen); `levy_jump_diffusion.py`/
`rough_volatility.py`/`options_greeks_features.py`/`svm_gradient_descent_classifier.py` hardcode
`KVUE/KMB`, itself a member of that same full-history-confirmed set. **None of them use the episodic/
PIT-confirmed pair set** from `research/wrds_deep_history_episodic_scan.py::
episodic_bhfdr_confirm_asof` (this session's own BUG-D106 fix, same day) or `pit_wfa.py`'s actual
point-in-time re-screened pairs.

**This is not a new bias — it is the SAME already-disclosed, already-quantified limitation from
§7.3.1** ("the confirmed-pair set is selected via a full-history screen that borrows from the future
relative to any real deployment date... a genuine point-in-time re-screen found zero pair overlap with
the known set and negative OOS Sharpe in every fold"). What was missing is that Findings #13–#19 never
stated this explicitly for the NEW modules — a reader could reasonably assume a freshly-built 2026-08-03
comparison arm had been built PIT-aware from the start, when in fact it inherits exactly the same
selection bias every other confirmed-pair-based analysis in this project already carries and discloses.
Stated here so the record is complete; each of §13–#19's individual entries above should be read with
this caveat, not as newly PIT-clean results.

**Priority for next session, not attempted here** (this is real engineering work, not a quick fix —
consistent with `pit_wfa.py`'s own multi-hour runtime and the deliberate, careful pace BUG-D99–D106
were each built at): build a PIT-aware pair-discovery adapter using `episodic_bhfdr_confirm_asof`
that these and future research scripts can call instead of (or alongside) `ml._discover_confirmed_pairs()`,
decide the `as_of_date` semantics for a "current" research run, systematically audit every research
script (not just these 7) for which pair-source it uses, and re-run the affected comparisons once
wired. Full priority item logged in `Development.md`.

---

## 28. Thread J Test 2 — Cointegration Regime Segmentation: Only 9.2% of Candidate Pair-Windows Are
Ever Cointegrated, Split Evenly Across Strong/Moderate/Weak [2026-08-13]

First real result from Thread J (scoped the same session, high priority per Ross). Built `research/
cointegration_regime_segmentation.py` to segment each candidate pair's full history into contiguous
cointegrated/non-cointegrated REGIME SPANS (not a single binary verdict), reusing the already-real,
already-verified per-window EG p-values from `wrds_deep_history_episodic_scan_tier3_windows.
parquet` (1,197,576 rows, no new statistical test introduced) rather than rebuilding a rolling EG
loop from scratch.

**The real design question**: a raw per-window state (p-value < alpha -> "coint") flips noisily
near genuine transitions and even within a stable regime (one borderline p-value shouldn't end a
10-year cointegrated stretch). Fixed via hysteresis: a state change only confirms once it persists
for >= `MIN_REGIME_WINDOWS=3` consecutive windows (reusing Finding #23's own already-validated
`min_windows_confirmed=3`, not a new invented number), with the regime's recorded start set to the
ONSET of that persistent run, not the later confirmation point. Verified synthetically first (5/5
checks, `debug/_verify_cointegration_regime_segmentation.py`): a single-window noise blip gets
correctly absorbed into the surrounding regime, while a real short-lived regime that clears the
3-window bar gets correctly detected as its own span.

**A real bug caught by running against real data, not just synthetic tests**: the first design
computed strength terciles (strong/moderate/weak) PER PAIR, from that pair's own coint spans. Real
data showed why this was wrong — 16,064 coint spans across 158,849 pairs, ~0.1 spans/pair, so almost
every pair has 0-1 coint spans and per-pair terciles are statistically meaningless (confirmed: the
first real run produced zero "weak" spans at all, only strong/moderate, because the tercile branch
requiring >=3 same-pair spans almost never triggered). Fixed: strength is now assigned as a GLOBAL
post-processing step (`assign_strength_terciles()`) across every pair's spans together — the
synthetic test's own check 5 was rewritten to test this cross-pair behavior, not the removed
per-pair path.

**Real result** (158,849 candidate pairs, full available WRDS/1D history):

| state | n_spans |
|---|---|
| not_coint | 158,011 |
| coint | 16,064 |

Of the 16,064 "coint" spans, strength splits almost exactly evenly by construction (global
terciles): strong=5,349, moderate=5,366, weak=5,349.

**UPDATE [2026-09-02]: superseded by the corrected-scale re-run.** The 158,849-candidate-pair
figure above predates the 2026-08-24 universe-undercount fix (§2 of `PAPER_MAGNITUDE.md`) by
eleven days. The corrected-scale re-run (same script, plus a second real bug found and fixed
along the way — see Finding #41 — that had caused ~90 consecutive crash-restarts) completed
2026-09-02 against the full ~44,700-symbol universe: **691,213 regime spans across 638,095
candidate pairs, not_coint=634,677, coint=56,536 (8.18%, down from 9.2% — a real, measured
change, not a reconfirmation)**. Strength terciles split evenly as before: strong=18,827,
moderate=18,883, weak=18,826, summing exactly to the coint count. `PAPER_MAGNITUDE.md`
§1.2/§4/§5/§11/§12 updated to the real numbers; see Finding #41 for the full root-cause story.

**Headline, honest finding**: only **9.2% of all detected regime spans across the full candidate
universe are ever genuinely cointegrated** at any point in their history — the overwhelming
majority of a pair's own history is spent in a non-cointegrated state, even among pairs that pass
the correlation prefilter enough to be episodic-scan candidates at all. This is a real, quantified
confirmation of Ross's original concern (a single fixed 10-year window and a binary confirmed/not
verdict obscures how rare and often short-lived genuine cointegration actually is within a pair's
full history) — not yet connected to Thread G-Full Tier 4's window-size sweep (Test 1, not run this
entry — the expensive multi-hour-per-grid-point piece, deferred pending Ross's go-ahead) or to
whether PIT confirmation's precision (Finding #23) differs by regime strength (the natural next
question this segmentation enables, not yet asked of the data).

Files: `research/cointegration_regime_segmentation.py` (new), `debug/_verify_cointegration_regime_
segmentation.py` (new, 5/5 pass), `output/research/cointegration_regime_segments.parquet` (new, real
run — 174,075 spans).

## 29. Three gs_quant-Inspired Comparison Arms + a BUG-D45 Retest at Scale [2026-08-13]

Ross reviewed `gs_quant` (Goldman Sachs' open-source quant toolkit — most of it Marquee-API-gated
and unusable without institutional credentials, but its `timeseries` submodule has ~40 standalone
functions) and asked for 3 ideas implemented as comparison arms, plus a retest of BUG-D45's
single-pair finding at scale. All 4 run against real cached `spread_series_*.parquet` data
(~471-474 confirmed pairs), not synthetic.

**29a. EWMA z-score vs. the production rolling-window z-score.** A real design correction was made
BEFORE building, not after: the original idea (swap just the std for EWMA, keep the existing
rolling mean) would have repeated BUG-D45's exact reverted mistake (decoupling mean/std windows).
Built correctly instead — EWMA for BOTH mean and std together (coupled, same halflife), matching
BUG-D45's own "single shared window" principle while still testing exponential vs. flat weighting.
Verified synthetically first (causality, no BUG-D45-style blowup on a drifting series), then run
for real: **mean correlation 0.846** between the two z-score series, **86.7% entry-signal
agreement** — a real, non-trivial ~13% disagreement rate, and neither method shows the BUG-D45
blowup pattern (frac|z|>10 ≈0.0001 for both). Not yet promoted to production — comparison-arm
result only.

**29b. Vol-swap-style (zero-mean, diff-based) risk-per-share estimate vs. the current level-std
convention** — motivated directly by this session's own Kelly-sizing investigation (Finding #25/
#26: risk-based sizing is unusable because `risk_per_share` estimates are too small relative to
account size). **Honest negative result, the opposite of the hoped-for direction**: the vol-swap
estimator produces risk-per-share values **~8.6x SMALLER** (median ratio 0.116) than the current
convention across 474 pairs — smaller risk-per-share means LARGER implied position sizes, which
would make the capital-overshoot/size-floor skip problem WORSE, not better. Mechanism: bar-to-bar
spread movement (what a diff-based vol estimator measures) is naturally much smaller than the
spread's full range within a window (what the current level-std measures) for a mean-reverting,
range-bound spread. A real, useful negative result — rules out this specific fix, doesn't leave the
question open.

**29c. BUG-D45 retest at scale — Ross's direct instruction ("a single case ... should be
retested")**: reconstructed BUG-D45's exact reverted design (decoupled short-std/long-mean z-score,
`OU_WINDOW_HALFLIFE_MULT_VOL=2x` half-life vs. the production `OU_WINDOW_HALFLIFE_MULT_MEAN=8x`)
and re-ran it across all 471 real cached pairs, not just the one (CRWD/DDOG) the original bug
report used. **The retest surfaces something more serious than the single-pair case suggested**:
96.2% of pairs (453/471) show the decoupled version as same-or-better by the `frac|z|>10`
diagnostic — the ORIGINAL single-pair framing ("decoupling is worse") doesn't hold as a general
rule for most pairs. But a real minority — **18 pairs (3.8%)** — show CATASTROPHIC blowups, not
just "somewhat worse" like CRWD/DDOG's reported 12.3%: e.g. `BXMT/ECL` shows a decoupled mean
z-score of **-88,141** with std **598,460**. This reframes BUG-D45's own finding — not "decoupling
is bad on average" (mostly false, per this retest) but "decoupling creates unbounded TAIL risk for
a real minority of pairs" (true, and arguably a stronger reason to keep the shared-window design
than the original single-pair framing implied, since a production system can't selectively apply a
change only to the 96.2% of pairs where it's safe without first knowing which 3.8% will blow up).

Files: `research/ewma_zscore_comparison.py`, `research/vol_swap_style_risk_estimate_comparison.py`,
`research/bug_d45_decoupled_std_retest.py` (all new), `debug/_verify_ewma_zscore_comparison.py`
(5/5... 4/4 checks pass), `debug/_verify_vol_swap_style_risk_estimate.py` (3/3 pass),
`output/research/{ewma_zscore_comparison,vol_swap_style_risk_estimate_comparison,
bug_d45_decoupled_std_retest}.parquet` (new, real runs).

## 30. Thread J Follow-Up — PIT Confirmation Precision by Early-Period Regime Strength: a Real,
Counter-Intuitive Signal at Small Sample Size [2026-08-13]

Directly connects two already-complete pieces of work rather than requiring a new expensive scan:
Finding #23's precision/recall methodology (does episodic BH-FDR confirmation actually hold up
forward) joined against Finding #28's regime segments (strong/moderate/weak cointegration-regime
strength, global terciles). Question: among pairs the methodology CONFIRMS, does precision differ
by the STRENGTH of the early-period regime that led to confirmation?

**Method**: reused Finding #23's own `build_pair_data`/`score_cell` functions directly (not
reimplemented) at its recommended cell (`min_windows_confirmed=3, alpha=0.10`), Tier 3 only
(BUG-D112 scope). For each of the resulting confirmed pairs, joined against Finding #28's regime
segments to find the coint-regime span overlapping ONLY the early (pre-confirmation-decision)
period — verified synthetically first (4/4 checks, including that a span overlapping only the LATE
period is correctly excluded, avoiding ground-truth leakage into the strength label).

**Real result**: 28 pairs confirmed at this cell (pooled precision 0.393, matching Finding #23's
own already-reported ballpark). By early-period regime strength:

| strength | precision | n_confirmed_pairs |
|---|---|---|
| strong | 0.304 | 23 |
| weak | 0.750 | 4 |
| moderate | 1.000 | 1 |

**Honest, counter-intuitive finding, reported with its real sample-size caveat front and center,
not buried**: pairs confirmed during a "strong" regime show LOWER precision than those confirmed
during a "weak" one — the opposite of the naive expectation. With n=23/4/1, this is NOT a
statistically robust result on its own (the weak/moderate buckets are far too small to trust in
isolation) — but the direction is real and worth flagging, not dismissed as noise reflexively. A
plausible, defensible mechanism: "winner's curse" / regression-to-the-mean — the most extreme-
looking early signal in a discovery sample (the "strong" bucket, by construction the lowest-
p-value tercile) is disproportionately likely to reflect a temporary statistical artifact that
reverts, rather than a genuinely robust relationship, precisely BECAUSE it was selected for being
extreme. This is a well-known statistical phenomenon generally, not invented for this result.

**What this means for Session 31's "Tiered" arm** (docs/FINDINGS.md's Step 5 writeup, which found
Tiered/Baseline were numerically identical because all pairs shared one PIT-confidence tier): this
result is a real, if small-sample, indication that a genuine strength-aware confidence tier COULD
add real value once tested at scale — but the DIRECTION found here (weaker early regimes showing
higher forward precision) is the opposite of what a naive "trust strong signals more" tiering
scheme would assume. Any future tier-weighting design should be validated against this direction,
not assumed to run the intuitive way, before being trusted.

Files: `research/pit_precision_by_regime_strength.py` (new), `debug/_verify_pit_precision_by_
regime_strength.py` (new, 4/4 pass), `output/research/pit_precision_by_regime_strength.parquet`

## 31. Thread G-Full Tier 2 — Backtest-Level Static Parameter OAT Screen: Exit/Stop Thresholds
Dominate, One Real Overfitting Flag, Five Parameters Show Zero Measured Effect [2026-08-13]

**Method**: same OAT-screen + overfitting-guard discipline as Thread G Phase 1 (Finding #25),
extended to the 12 Tier 2 backtest.py/portfolio_sim.py-level constants scoped in the master plan
(`stop_zscore`, `exit_zscore`, `max_hold_multiplier`, `corr_exit_threshold`, `corr_exit_window`,
`min_half_life_bars`, `max_half_life`, `flat_risk_pct`, `n_shares_per_trade`,
`commission_per_share`, `slippage_bps`, `max_concentration_pct`). Each perturbed individually (grid
of discrete alternative values including the current default) against the Purity arm's IS+OOS
portfolio Sharpe (`--capital-sim`), ranked by effect size (range of Sharpe across the grid), with
the IS-best value's OOS rank checked as an overfitting guard (a param whose IS-optimal setting
ranks poorly OOS is flagged, not silently trusted).

**Real result, effect-size ranking**:

| Parameter | IS range | OOS range | Overfit flag |
|---|---|---|---|
| `max_hold_multiplier` | 1.416 (largest IS) | 0.266 | No |
| `exit_zscore` | 0.918 | 0.864 (largest OOS) | No |
| `stop_zscore` | 0.421 | 0.577 | No |
| `min_half_life_bars` | 0.539 | 0.402 | **Yes** — IS-best=20 bars, OOS-best=1 bar, IS-best's OOS rank 4/5 |
| `n_shares_per_trade` | 0.614 | 0.141 | No |
| `commission_per_share` | 0.089 | 0.071 | No |
| `slippage_bps` | 0.015 | 0.016 | No |
| `corr_exit_threshold`, `corr_exit_window`, `max_half_life`, `flat_risk_pct`, `max_concentration_pct` | 0.000 | 0.000 | N/A |

**`exit_zscore` and `stop_zscore` are the two parameters with a real, consistent, non-trivial
effect on BOTH splits** (not just IS-only, which would itself be a red flag) — genuine candidates
for the Phase-2 interaction-study survivor list, same role `entry_zscore` played in Thread G
Phase 1. `max_hold_multiplier` and `n_shares_per_trade` show a real IS effect but a much smaller
OOS one — not flagged as outright overfitting (their IS-best value's OOS rank isn't in the bottom
half), but weaker survivors than the exit/stop pair, worth including in Phase 2 only as a lower
priority.

**One real overfitting flag, stated honestly**: `min_half_life_bars` is the one parameter where the
IS-optimal setting (20 bars) performs poorly OOS (rank 4 of 5) while the OOS-optimal setting is a
very different value (1 bar) — a textbook overfitting signature at this grid resolution. This
parameter should NOT be tuned to its IS-optimal value in production without further, more granular
validation.

**Five parameters show EXACTLY zero measured effect on both splits, flagged as an open question,
not silently accepted as "confirmed irrelevant"**: `corr_exit_threshold`, `corr_exit_window`,
`max_half_life`, `flat_risk_pct`, `max_concentration_pct` all produced byte-identical Sharpe across
every grid value tested (visible directly in the raw log — e.g. every `MAX_CONCENTRATION_PCT` grid
point from 0.1 to 0.5 produced identical `sharpe=-0.6789 n_taken=146` IS / `sharpe=-0.8336
n_taken=105` OOS). Two honestly distinct explanations are possible and NOT yet distinguished: (a)
these parameters are genuinely non-binding at this run's actual trade set (e.g. `max_concentration_pct`
never binds because the realized position sizes never approach the cap), which would be a real,
legitimate null result; or (b) the CLI override for these 5 parameters isn't actually reaching the
backtest engine (a wiring bug in the Tier 2 registry entries, not a property of the strategy).
**Not yet checked which** — flagged here as a required follow-up before trusting the zero-effect
result at face value, per this project's own "negative results are real results, but only once
verified as genuinely negative and not a bug" discipline.

**Sequencing**: per the master plan's Thread G-Full design, this feeds a future cross-tier
interaction study once Tier 3/4 screens also complete — `exit_zscore`/`stop_zscore` join
`entry_zscore` (Finding #25/#27) as confirmed Phase-2 survivors from the backtest-level tier.

Files: `research/parameter_sensitivity_screen.py` (Tier 2 registry extension, already built),
`output/research/param_sensitivity/tier2_oat_results.parquet` (108 rows),
`output/research/param_sensitivity/tier2_overfitting_guard.parquet`,
`output/research/param_sensitivity/tier2_run.log` (raw run log, real numbers cited above verified
directly against it, not summarized from memory).

**Addendum (2026-08-13, same day) — the zero-effect investigation resolved, two distinct root
causes found, one fixed**: per Ross's explicit "investigate" instruction, traced all 5 zero-effect
parameters directly against the actual codebase rather than leaving the ambiguity open.

- **`corr_exit_threshold`, `corr_exit_window`, `max_concentration_pct`, `max_half_life` are DEAD
  config constants.** All 4 are declared in `config.py`, described (in `max_concentration_pct`'s
  and `corr_exit_threshold`'s case, directly in `backtest.py`'s own module docstring, as if they
  were active exit/sizing conditions) — but a codebase-wide grep confirms none of the 4 is actually
  READ by any executable code path anywhere in the project. `max_concentration_pct` was already
  independently caught once before (a "Tier 6 doc-drift fix, Grand Sweep 2026-07-20" comment sitting
  directly in `backtest.py` lines 10-19, confirming the exact same "documented as active, never
  wired in" finding). `max_half_life` is additionally mis-scoped for this sweep methodology even if
  it WERE implemented: its own comment describes it as a pair-SELECTION-time ceiling (would belong
  in `analysis.py`'s screening funnel, filtering candidates before `backtest.py` ever runs), not a
  backtest-time parameter at all — sweeping it against an ALREADY-FIXED `purity_pairs.parquet` file
  could never show an effect regardless of implementation status. **Left unimplemented, not fixed
  unilaterally** — building 4 new pieces of trading logic (a correlation-based structural-breakdown
  exit, a live concentration cap, a redesigned half-life screening step) is new-methodology work
  requiring Ross's sign-off per this project's own Working Style rule, not something to add as a
  side effect of a sensitivity-screen bug hunt. Real open decision for Ross: implement these 4
  described-but-dead features for real, or retire them from `config.py`/the Tier 2 registry (as
  currently written, re-sweeping them will always report a misleading "zero effect" that actually
  means "not wired in," not a genuine null finding).
- **`flat_risk_pct` was a genuine, fixable wiring bug — fixed.** `portfolio_sim.py` read
  `Config.BACKTEST.FLAT_RISK_PCT` into a MODULE-LEVEL constant (`_FLAT_RISK_PCT`) once, at import
  time. `backtest.py`'s `--override FLAT_RISK_PCT=X` mutates a per-run `copy.copy()` of
  `Config.BACKTEST` — a DIFFERENT object from the global `Config.BACKTEST` that `portfolio_sim.py`
  read from, so the override could never reach it regardless of import order. Fixed by adding an
  explicit `flat_risk_pct` parameter to `replay_portfolio()` (default `None` preserves the original
  module-constant behavior for every other existing caller), with `backtest.py` now passing
  `_backtest_cfg.FLAT_RISK_PCT` through explicitly at the `--capital-sim` call site. Verified
  synthetically (`debug/_verify_flat_risk_pct_override.py`, 2/2 checks: doubling `flat_risk_pct`
  exactly doubles target notional under `flat_2pct` sizing; omitting the parameter reproduces the
  original default-constant behavior) before trusting the fix. Re-ran the sweep against the fixed
  code (`--only flat_risk_pct`): **still exactly zero effect** on both splits, but now for a fully
  understood, different reason — this Tier 2 sweep's `capital_sizing` is `"fixed"` throughout
  (`parameter_sensitivity_screen.py`'s own default), and the `"fixed"` sizing branch never consults
  `risk_fraction`/`FLAT_RISK_PCT` at all (`target_notional = original_notional`, full stop — see
  `portfolio_sim.py`'s `replay_portfolio`). `FLAT_RISK_PCT` only matters under `flat_2pct` or
  Kelly-family sizing, neither of which this sweep exercises. The import-time wiring bug was real
  and is now fixed (confirmed by the synthetic test doubling the parameter and seeing target
  notional exactly double), but it was never the reason THIS specific sweep showed zero effect — a
  second, independent reason (wrong sizing-method context for this parameter to matter in) was
  masking the first. `flat_risk_pct` only becomes a meaningful Tier 2 sweep target once run under
  `--capital-sizing flat_2pct` specifically, not the default `fixed`.
(new, real run).

## 32. Thread M's Real Purpose Run — Both Options Built, Verified, and Run Against CAMARF's Own
Realized Returns; the Honest Result Is "Not Enough Trade History Yet," Not a Fabricated Alpha
[2026-08-14]

**Expanded Option A from 6 to 17 characteristics** (Ross: "let's use them and more if available"),
adding 2-3 more per category (value: `at_me`/`ni_me`/`sale_me`; profitability/quality: `gp_at`/
`f_score`/`o_score`; investment: `capx_gr1`/`noa_gr1a`; low-risk: `ivol_capm_252d`) plus a wholly
new liquidity category (`dolvol_126d`, `ami_126d`) the original 6 didn't touch. Re-verified
synthetically (5/5, unchanged mechanics), re-ran against real WRDS data — all 17 factors produced
plausible monthly return statistics, and the momentum validation against Fama-French/Carhart's
trusted `umd` factor held at the same 0.8005 correlation (unaffected, since momentum's own
construction wasn't touched by the expansion).

**Built `research/jkp_thread_m_driver.py`**, connecting both options to CAMARF's actual realized
Step 5 backtest-arm returns (`output/research/step5_arm_results/real_*_trades_capsim.parquet`) for
every arm (baseline/hybrid/purity/tiered) x split (IS/OOS) combination -- reusing Thread F Part A's
`build_daily_return_series` directly, aggregated to monthly to match JKP's frequency. Verified
synthetically first (`debug/_verify_jkp_thread_m_driver.py`, 4 checks: known-relationship recovery,
insufficient-overlap rejection, DOF-trustworthiness flagging, sparse-trading flagging).

**A real bug found via the run itself (4th recurrence this session of the same bug class)**:
`build_portfolio_characteristic_exposure`'s `np.nanmean()` call crashed on a genuine pandas `pd.NA`
value returned by `raw_sql()` (`TypeError: boolean value of NA is ambiguous`) -- the exact same root
cause already found and fixed 3 times earlier this session in unrelated files (`data_wrds.py`'s
`build_full_market_label_map`, `international_liquidity_filter.py`'s currency lookup). Fixed by
converting to a definite plain float via `pd.notna()` before any numpy operation touches the value.
A deliberate codebase-wide grep for the same pattern (raw WRDS-fetched values feeding directly into
`np.isnan`/`np.nanmean`/truthiness checks without an explicit float conversion) found no further
un-fixed instances.

**The real, honest headline result**: every single one of the 20 regressions run (Option A's core-6
and full-17 factor sets, Option B's raw-characteristic exposure, across all 8 arm/split
combinations) is flagged **NOT TRUSTWORTHY** -- not because the pipeline is broken (both options are
independently verified correct via synthetic tests with known ground-truth relationships), but
because CAMARF's own realized trade history is currently too sparse to support a monthly factor
regression at all. Direct inspection of the underlying monthly return series confirms this
concretely: the `baseline` and `tiered` arms are **81-82% exact-zero-return months** (17 of 21),
with real P&L concentrated in only 3-4 months total; even the more actively-traded `purity`/`hybrid`
arms are 40-57% zero months. A regression against a return series this sparse produces spuriously
extreme-looking statistics that don't reflect genuine risk-factor exposure (observed before the
sparsity guard was added: |t-stats| up to 67, an implausible magnitude for ~20-30 monthly
observations) -- the guard now catches and flags this explicitly rather than letting a misleadingly
"significant"-looking alpha stand unchallenged.

**What this means, stated plainly**: Thread M cannot currently answer its own scoped question
("does CAMARF's edge look like known style-factor exposure in disguise") with any real confidence,
for a data-volume reason unrelated to either option's methodology. This connects directly to this
project's already-documented ML-gate constraint (Session 22-27 notes: "~2 weeks from 2026-06-30 for
training data accumulation") -- CAMARF's realized trade count is still accumulating, and Thread M is
a second, independent illustration of the same underlying limitation (not enough closed trades yet
for statistically meaningful post-hoc analysis), not a new problem. **Re-run this driver once trade
count/density has grown substantially** (the pipeline itself needs no further changes) -- until then,
no alpha/loading number from this thread should be cited as a real finding in `PAPER.md` or
elsewhere.

Files: `research/jkp_factor_portfolio_construction.py` (17-factor expansion),
`research/jkp_raw_characteristic_regression.py` (pd.NA fix), `research/jkp_thread_m_driver.py`
(new), `debug/_verify_jkp_thread_m_driver.py` (new, 4/4 pass, includes the sparse-trading guard
check), `debug/_verify_jkp_raw_characteristic_regression.py` (Check 2b added, reproduces the real
pd.NA bug with a genuine nullable-dtype column), `output/research/jkp_factor_portfolios_monthly.parquet`
(17-factor real output), `output/research/jkp_thread_m_regression_results.parquet` (20 regression
results, all honestly flagged untrustworthy).

## 33. Thread G-Full's 4 Dead Config Constants -- 3 Implemented For Real Comparison (Not Retired),
One Real Bug Found and Fixed Along the Way [2026-08-14]

Per Ross's explicit direction ("instead of deleting the 4 dead config constants can we implement
for comparison first?") -- all 3 backtest.py/portfolio_sim.py-level dead constants from Finding
#31's investigation were built as real, opt-in comparison arms (not silently made the new default),
each verified synthetically against the REAL BacktestEngine.run()/portfolio_sim.replay_portfolio()
(not a re-implemented copy of the logic) before being run for real. `MAX_HALF_LIFE_DAYS`/
`MIN_HALF_LIFE_DAYS` (the SEPARATE, already-implemented `analysis.py`-level screening-tier
constants) are untouched -- this entry is about the 3 backtest.py-tier ones.

**`--storm-max-half-life-filter`**: skip entry if `half_life_at_entry > MAX_HALF_LIFE`, symmetric
to the existing `MIN_HALF_LIFE_BARS` floor. Verified
(`debug/_verify_dead_constants_comparison_arms.py` Check 1): correctly skips a synthetic entry with
half_life=80 (> default MAX_HALF_LIFE=50). Real result against Purity pairs: **IS Sharpe -1.4333
(193 trades, vs. baseline -0.6789/146), OOS Sharpe -1.9772 (119 trades, vs. baseline -0.8336/105)**
-- WORSE on both splits, and MORE trades taken, not fewer. Real, disclosed finding: filtering pairs
whose entry-time half-life exceeds 50 bars doesn't help and may be actively harmful at this
snapshot -- plausibly because slower-reverting entries excluded by this filter were, on net, some
of the better-performing trades, not noise being correctly screened out. Divergence, not
convergence, with the naive expectation that a tighter half-life ceiling should help.

**`--storm-real-corr-exit`**: a genuine structural-breakdown exit using `CORR_EXIT_THRESHOLD`
against the already-available, point-in-time `coint_fraction_rolling_t` series -- a disclosed
substitution for leg-price correlation (not available in `spread_series` files without a new
data-loading pipeline), additive to the existing z-widening `corr_exit` heuristic (priority #4),
not a replacement. **A real bug found and fixed during this build**: the first version, with no
debounce, produced catastrophic overtrading -- 269,707 trades across the Purity pairs (vs. 146
baseline) from `coint_fraction_rolling_t` chattering back and forth across the 0.20 threshold bar
to bar, triggering immediate exit/re-entry cycles. Fixed by applying the SAME `hold_bars > 5`
debounce guard the existing z-widening heuristic (condition #4) already uses for exactly this
failure mode -- not a new mechanism invented, just consistently applying the codebase's own
established convention to the new condition. Re-verified synthetically, then re-run for real: **IS
Sharpe -6.4701 (951 trades), OOS Sharpe -5.4733 (775 trades)** -- vastly worse than baseline even
with debouncing, and still 6-7x baseline's trade count. Real, disclosed finding: even debounced,
`coint_fraction_rolling_t` crosses below `CORR_EXIT_THRESHOLD=0.20` far more often than a genuine
rare "structural breakdown" event should, causing destructive overtrading -- either the 0.20
threshold is miscalibrated for this use (too loose), or `coint_fraction_rolling_t`'s own rolling
window is too short/noisy to serve as a real-time exit trigger without additional smoothing. A
clear, understood negative result, not a surprising unexplained one.

**`--concentration-cap`**: caps a single position's target notional at `MAX_CONCENTRATION_PCT`
(default 0.20) of CURRENT equity, enforced in `portfolio_sim.py`'s unified replay engine (the
correct architectural home -- concentration is inherently portfolio-level/cross-pair, unlike the
other two which are genuinely per-pair). Verified (`debug/_verify_flat_risk_pct_override.py` Check
3): a position whose uncapped target notional would exceed the cap is correctly clamped exactly to
it. Real result against Purity pairs: **IS Sharpe -0.6349 (167 trades), OOS Sharpe -0.8972 (116
trades)** -- essentially unchanged from baseline (-0.6789/146, -0.8336/105). Real, disclosed
finding: `MAX_CONCENTRATION_PCT=0.20`'s default value rarely BINDS for this pairs set under `fixed`
sizing at $100k starting capital -- the strategy's own default position sizes are already comfortably
under the cap most of the time, so this constraint has near-zero real-world effect at its default
value (a legitimate near-null result, not evidence the mechanism itself is broken -- confirmed
working correctly via the synthetic test's much more aggressive sizing parameters).

**No promotion to production decided here** -- these are disclosed comparison-arm results per this
project's own comparison-arm-before-production discipline, not a recommendation to adopt any of
the 3 by default. Two of three (max_half_life_filter, real_corr_exit) show real, moderate-to-severe
degradation versus baseline; concentration_cap shows a real near-null effect at its current default
threshold.

Files: `backtest.py` (3 new `--storm-*`/`--concentration-cap` flags + engine logic),
`portfolio_sim.py` (concentration_cap parameter), `debug/_verify_dead_constants_comparison_arms.py`
(new, 2/2 checks), `debug/_verify_flat_risk_pct_override.py` (Check 3 added, concentration_cap),
real output files under `output/backtest/portfolio_layer1*{maxhlfilter,realcorrexit}*capsim*.parquet`
and `output/backtest/portfolio_layer1*_ccap.parquet`.

## 34. Thread L -- Local Event-Study Framework Built and Run For Real [2026-08-14]

Built `research/event_study_framework.py`, the CAMARF-native equivalent of gs-quant's Marquee-gated
`timeseries.event_study` module (`frame_timeseries_around_events`/`event_impact_analysis`), using
only already-cached local data -- `earnings.py::EarningsCalendar` (real quarterly earnings dates)
and macro.py's regime classification output (transition dates derived generically here, not a new
macro.py function). Core primitive `frame_series_around_events(series, event_dates, window_before,
window_after)` re-indexes any series to RELATIVE bar offset from each event (0 = event bar) --
verified synthetically first (`debug/_verify_event_study_framework.py`, 5/5 checks: exact window
recovery, multi-event independence, out-of-range event exclusion, correct transition-date detection,
both-legs earnings-date union).

**Real run, ADBE/MDT (Purity pair)**: 48 earnings events framed at +/-10 trading days. A real,
plausible pattern: z-score standard deviation NARROWS from ~1.55 at 10 days before an earnings
announcement to ~1.22 at 10 days after -- consistent with earnings-related uncertainty resolving
post-announcement (a real, disclosed descriptive observation, not a new trading signal -- per this
thread's own explicit non-goal, lead-lag/event-driven PREDICTION already has 3 independent null
results on this universe, Finding #11 area; this is descriptive regime-framing only).

Not yet run against macro regime transitions (the `frame_pair_around_macro_transition` wrapper is
built and would need a real MacroResult column aligned to a pair's spread_series index -- a
mechanical follow-up, not a design gap).

Files: `research/event_study_framework.py` (new), `debug/_verify_event_study_framework.py` (new,
5/5 pass).

## 35. Thread N #5 -- VaR Model Backtesting/Calibration Check (Basel-Style): a Real Degenerate-Data
Artifact Caught and Fixed, Purity/Hybrid's 99% VaR Is Genuinely Well-Calibrated [2026-08-14]

**Stated plainly, per Thread N's own framing**: this is a risk-METHODOLOGY comparison, not a legal
compliance certification. Sequenced first per that thread's own design (#5 before #1) -- answers
"is a VaR framework even meaningful for this strategy" before any VaR-based position sizing tries
to use one.

Built `research/var_backtest_calibration.py`: rolling, strictly causal historical VaR (empirical
percentile of a trailing window, no distributional assumption), Basel-style exception counting
against CAMARF's real Step 5 daily P&L (reusing `build_daily_return_series` directly). Verified
synthetically first (`debug/_verify_var_backtest_calibration.py`, 4 checks: causal no-lookahead
confirmation, known-exception recovery, traffic-light threshold correctness, a genuinely
well-calibrated synthetic model correctly landing green).

**A real degenerate-data artifact found via the run itself, not glossed over**: the first real run
showed baseline/tiered arms with "0 exceptions across 392 observations" -- looking like a perfect
calibration result. Direct investigation confirmed this was entirely artifactual: ALL 392
observations had a degenerate VaR estimate (`var_t <= 0`), a direct consequence of Thread M's
already-documented finding (baseline/tiered are 81-82% exact-zero-return days) -- a trailing window
that's mostly zeros produces a zero empirical percentile, and `count_exceptions`'s own `var_t > 0`
guard silently excluded every single one of these from consideration, leaving genuinely ZERO
meaningful observations behind a misleadingly clean "0/392" headline. Fixed: `count_exceptions` now
reports `n_obs` as only the non-degenerate count, with `n_degenerate`/`n_attempted` surfaced
separately so this can't be silently misread again.

**A second real methodology point found and disclosed**: Basel's own 4/9 exception-count
traffic-light thresholds are calibrated specifically for 99% VaR (1% expected daily exceedance) --
applying the same raw thresholds to a 95% VaR result (5% expected) will show "red" even for a
PERFECTLY calibrated model, since 5% inherently exceeds a threshold built around 1%. Disclosed
directly in `basel_traffic_light()`'s docstring and the driver's own output (an explicit caveat
line on every 95%-confidence result), not silently misapplied.

**The real, honest result after both fixes**: baseline/tiered remain genuinely data-starved (0
meaningful 95%-VaR observations; only 92 thin observations at 99%, still showing exceptions=0 --
consistent with, not contradicting, Thread M's "not enough trade history yet" finding). Purity and
Hybrid (the more actively-traded arms, 732 total observations) show a REAL, positive calibration
result at 99% VaR: exception rates of **1.4-1.8%** against a 1% target -- close enough to be
plausible for a well-functioning historical VaR model at this sample size, landing green/yellow
(not red) on Basel's own scale. 95% VaR exception rates (5.1-5.8% against a 5% target) are similarly
close to well-calibrated, though the traffic-light label itself isn't meaningful at that confidence
level per the caveat above.

**What this means for Thread N #1 (VaR-based position sizing, the next sub-arm)**: a genuine green
light, with a real caveat -- 99% VaR appears usable as a sizing input for the Purity/Hybrid arms
specifically (where real observation counts exist), but NOT yet for baseline/tiered, which remain
too data-starved for any VaR-based methodology to be meaningfully validated first.

Files: `research/var_backtest_calibration.py` (new), `debug/_verify_var_backtest_calibration.py`
(new, 4/4 pass), `output/research/var_backtest_calibration_results.parquet` (16 real results).

## 36. Thread N #2 -- Leverage/Gross Exposure Cap Comparison Arm: a Real Architectural Discovery
(No-Leverage Already Implicit) and a Mixed, Honest Real Result [2026-08-14]

Built `--leverage-cap` (portfolio_sim.py's `replay_portfolio`), capping TOTAL gross exposure (all
open positions combined, not a single position like `concentration_cap`) at a fixed multiple of
current equity -- matches the UCITS commitment-approach / '40 Act Section 18 asset-coverage
convention.

**A real architectural property found while verifying this, not a bug**: `portfolio_sim.py`'s
EXISTING capital-availability constraint (`available = current_equity - committed_now`) already
implicitly enforces a de facto `leverage_cap=1.0` by construction -- positions can never be sized
beyond available cash regardless of `leverage_cap`, since this engine has no borrowing/margin
mechanism anywhere. This means `leverage_cap >= 1.0` is ALWAYS a no-op against the existing default
behavior; the parameter only has a genuinely distinct effect for values < 1.0 (a real, TIGHTER
constraint than what's already implicit). Verified directly (`debug/_verify_flat_risk_pct_override.py`
Check 4): two overlapping positions' unlevered combined notional already saturates at exactly 100%
of equity by itself; `leverage_cap=0.5` correctly clamps that to 50%.

**Real result against Purity pairs at `leverage_cap=0.5`**: IS Sharpe -0.4320 (128 trades, vs.
baseline -0.6789/146) -- an IMPROVEMENT; OOS Sharpe -0.9654 (88 trades, vs. baseline -0.8336/105) --
a DEGRADATION. A genuinely mixed, honest result, not a clean win or loss -- tighter gross-exposure
constraint helped in-sample but hurt out-of-sample, consistent with reduced position sizing cutting
both the strategy's losses AND its (limited) gains roughly proportionally, with the net direction
differing by split. Not evidence either for or against adopting a leverage cap by default.

Files: `portfolio_sim.py` (leverage_cap parameter), `backtest.py` (`--leverage-cap` flag),
`debug/_verify_flat_risk_pct_override.py` (Check 4).

## 37. Liquidity Bar Filter -- Real Entry-Filter Comparison Arm, Mixed Result [2026-08-14]

Built `--storm-liquidity-bar-filter` (backtest.py), reusing `research/liquidity_bar_masking.py`'s
`liquid_bar_mask` -- skips entry if either leg's OWN dollar volume that day falls below
`MIN_DOLLAR_VOLUME`. Verified synthetically (`debug/_verify_dead_constants_comparison_arms.py`
Check 3): a pair whose only entry-qualifying bar coincides with one leg being illiquid produces
zero trades with the flag on.

**Real result against Purity pairs**: IS Sharpe -0.5782 (93 trades, vs. baseline -0.6789/146) --
a real improvement; OOS Sharpe -0.9153 (136 trades, vs. baseline -0.8336/105) -- a real
degradation, and OOS trade count went UP despite the filter being strictly more restrictive at
entry (same mechanism already seen with `max_half_life_filter`: skipping some entries frees
capacity for other, later entries that would have been blocked by an already-open position).
Genuinely mixed -- not a clean confirmation that illiquid-bar contamination explains the negative
Sharpe, consistent with Finding on the bar-masking investigation (the originally-hypothesized
mechanism doesn't dominate on this universe). Still a legitimate signal-quality/fill-realism
filter worth having as an option, just not a fix for the Sharpe problem on its own.

Files: `backtest.py` (`--storm-liquidity-bar-filter`), `debug/_verify_dead_constants_comparison_arms.py`
(Check 3 added).

## 38. Ridge-Regularized Hedge Ratio — Clean Negative on Full-Sample Estimates, With a Real Scope
Mismatch to the Motivating Hypothesis [2026-08-10]

(Numbered out of strict chronological order — dated 2026-08-10, but originally mis-numbered as a
duplicate "## 24." and moved here 2026-08-20 to resolve that collision without renumbering/breaking
any of the many existing cross-references to Findings #25-#37 elsewhere in the codebase. Content
unchanged from the original entry.)

Ross's question: does ridge (L2-regularized) regression improve hedge-ratio estimation over the
existing production methods (`analysis.py::HedgeRatioEstimator` — OLS, TLS, Kalman)? Motivated by
this session's intraday work — shorter, noisier rolling windows are exactly the regime where an
unregularized OLS slope is most exposed to overfitting a handful of noisy observations, and ridge's
whole point is trading a little bias for less variance there.

**Method** (`research/ridge_hedge_ratio_comparison.py`, new): `ridge_rolling` is a structural copy
of `HedgeRatioEstimator.ols_rolling` (byte-for-byte identical causal windowing convention) with one
change — the OLS normal equation's `var(B)` denominator becomes `var(B)*(1+k)`, the closed-form
univariate ridge shrinkage. `k` is expressed as a *fraction* of that window's own `var(B)`, not a
fixed absolute lambda, so it's comparable across pairs with wildly different price-level variances
— a real design choice, not an arbitrary convenience. Grid: `k ∈ {0, 0.01, 0.05, 0.10, 0.25, 0.50}`
(`k=0` is exactly plain OLS, verified bit-identical to `ols_rolling`, not just claimed). Evaluated
via ADF p-value on the resulting spread — a lower p-value at a given `k` than at `k=0` counts as
"improved."

**A real bug caught against real data, not synthetic data** (the exact reason this project runs
synthetic checks first but doesn't stop there): `research/aligned_pair_loader.py::load_aligned_pair`
uses `DataAligner.align_universe`'s default (`drop_data_gap_rows=False`, correct for the main
pipeline's cross-*symbol* dense-matrix construction) which does **not** guarantee the two returned
per-pair series come back the same length. `IQV/Q@1D` crashed the first real run with a length
mismatch (252 vs. 161 rows — `IQV` has a shorter cached history, already noted elsewhere in this
project as "recently listed"). `research/coint_frac_window_grid.py`'s own `build_pair_data` already
has this exact requirement and handles it with an explicit inner join before treating the two series
as parallel arrays — mirrored here (the same fix) rather than assuming equal length.

**A real, useful catch inside the synthetic verification itself, worth recording as process.** The
first version of check 4 (does ridge help on a short, noisy window — the actual motivating use case)
used WIN RATE: does ridge land closer to the true beta than OLS more than half the time across many
trials? It failed, 8/30. Not a broken test — a real statistical fact: ridge trades variance for
*bias* (shrinks toward 0), and with a true beta of 1.2 (not near 0), that bias cost is real. Win rate
is the wrong criterion for a bias-variance tradeoff; the textbook-correct one is **mean squared
error** averaged across trials, which ridge (k=0.1) did lower — 0.1327 vs. OLS's 0.1472 over 200
trials, ~10% reduction — even while still "losing" per-trial most of the time. Fixed the check to
use MSE; 7/7 pass.

**Real result, all 3 current confirmed pairs, full-sample point estimate**: ridge makes the spread
*monotonically less stationary* (higher ADF p-value) at **every single tested `k`, on all 3 pairs**
— e.g. `PNC/ZION@4h`: ADF p rises from 2.1e-7 (k=0, already extremely stationary) to 0.55 (k=0.50,
essentially non-stationary); `IQV/Q@1D`: 0.138 → 0.254; `KVUE/KMB@3m`: 0.00027 → 0.192. Zero
improvements across the full 3-pair × 6-k grid (0/3 at every k).

**Why this is a clean negative and not a contradiction of the synthetic MSE result above — a real
scope mismatch worth stating plainly, not glossed over.** This real-data test used
`ridge_rolling`'s **full-sample** point estimate — thousands of bars even for the shortest pair
(`KVUE/KMB@3m` alone has ~4,160 cached 3m bars). The synthetic check that found a real ridge benefit
specifically used a **short** window (60 bars) with **large** relative noise — exactly the regime
ridge's bias-variance tradeoff is supposed to help in. These 3 pairs were selected *because* they're
already strongly, confidently cointegrated by a strict full-history screen — ample data, a
well-determined OLS estimate, no variance problem for ridge to fix, so shrinkage only ever costs
bias here. **This test did not actually evaluate the motivating hypothesis** (does ridge help the
*rolling, short-window* hedge ratio used for live per-bar spread tracking, especially on noisy
intraday data) — it evaluated a different, mismatched regime where a negative result is close to
theoretically expected. Real follow-up, not attempted here: re-run this same comparison using
`ridge_rolling`'s *rolling* series (not the full-sample point estimate) against the intraday
episodic scan's own short windows (Step 2/Thread A of the current master plan) once that data
exists, which is the setting this was actually motivated by.

**Honest conclusion.** Ridge does not help CAMARF's current 3-pair confirmed set's full-sample hedge
ratio — a real, clean, verified negative result, not a failed feature (per this project's rule 8, a
negative result with a well-understood mechanism is exactly as valuable as a positive one). Whether
it helps the actual motivating case (short intraday rolling windows) remains untested and is a
concrete, scoped follow-up, not resolved by this result either way.

Files: `research/ridge_hedge_ratio_comparison.py` (new), `debug/_verify_ridge_hedge_ratio_
comparison.py` (new, 7/7 pass), `output/research/ridge_hedge_ratio_comparison.parquet` (new, real
run).

## 39. Hardcoded Pair-List Fix — First Real Results Against the Live Confirmed Set [2026-08-24]

Ross's direction: no research script should hardcode which pairs it tests — every script must use
either the current confirmed-pair set (`output/results/*/pairs.parquet`) or the full universe, so
results always reflect CAMARF's actual live state, not a frozen snapshot from whenever the script was
written. A codebase-wide grep found ~20 `research/*.py` scripts violating this — 12 shared the exact
same hand-picked 9-pair list (`LNT/VTR`, `CMS/DUK`, etc.), 3 hardcoded `KVUE/KMB` under a
misleadingly-named `_CONFIRMED_PAIRS` constant (itself flagged 2026-08-03 in the retroactive
disclosure above `KVUE/KMB` was real at the time, just frozen since), and a handful of others carried
their own one-off hardcoded lists. Fixed via a new shared `research/pair_source.py`
(`confirmed_pairs_list()`/`candidate_pairs_list()`, reading the same `output/results/*/pairs.parquet`
glob `bayesian_pair_confirmation.py` already used correctly) that all ~20 files now call instead of
carrying their own copy. One deliberate exception, not silently skipped: `filter_relevance_sweep_1h.py`
hardcodes PNC/ZION and SPY/VOO because the script's entire purpose is forensically reconstructing a
specific documented 2026-07-21 persistence-gap incident — those symbols ARE the historical record
being recovered, not a stand-in for "current confirmed pairs." Verified via
`debug/_verify_pair_source.py` (6/6 pass, synthetic — stale-dir exclusion, tf_label filtering,
dedup) plus a live check against real `output/results/` data on both machines before restarting the
overnight pipeline from its 44/195-stage checkpoint on the corrected code.

**CachyOS's live confirmed set as of this run: 2 pairs — `KVUE/KMB@3m` and `PNC/ZION@4h`** (thinner
and at different timeframes than the old hardcoded 9-pair set, which was never even a subset of the
current confirmed set — none of `LNT/VTR`, `AME/MAR`, etc. are currently confirmed). First results
from the corrected scripts, pulled as each completed in the pipeline's alphabetical research-script
sweep:

- **`breakout_vs_reversion.py`** (`--tf 1hr`, both confirmed pairs): mean-reversion strongly
  dominates breakout on both pairs — `KVUE/KMB`: MR n=79 win=100% total_pnl_z=244.95 vs. BO n=157
  win=7% total_pnl_z=-166.10; `PNC/ZION`: MR n=84 win=100% total_pnl_z=244.27 vs. BO n=136 win=4%
  total_pnl_z=-169.52. Entry/exit sweep best mean-reversion combo: entry=3.0, exit=0.25 ->
  sharpe_like=3.900 (n=61, win=100%); best breakout combo is still net-negative (sharpe_like=-0.630).
  A 100% win rate on n=79/84 trades is a small, non-independent sample (same 2 pairs, same regime) —
  read as "mean-reversion clearly beats breakout on these two pairs' recent history," not as a
  production-ready Sharpe.
- **`cross_timeframe_divergence.py`**: deep-history group (1hr/4hr/1day) — 2/2 pairs show a
  CONSISTENT significance verdict across all 3 TFs; shallow-history group (15min/30min/1hr) —
  significance rate drops from 2/2 pairs at 15min/30min to 1/2 at 1hr (`KVUE/KMB` p=0.0876 vs.
  `PNC/ZION` p=0.0250), correlation(log10(bars/day), mean log10(p)) = -0.995 in that group — consistent
  with this project's existing granularity/significance finding, now confirmed on the live pair set
  instead of the frozen one.
- **`fdr_method_comparison.py`** (`--tf 1h`, full current 1h universe, m=89 candidates): 0/89 survive
  under all 4 correction methods (step-up BH, Benjamini-Yekutieli, two-stage TSBH, fixed Bonferroni) —
  a clean, consistent null across every method tested, alpha=0.05. Neither confirmed pair is at 1h
  (`KVUE/KMB@3m`, `PNC/ZION@4h`), so the "known pairs" watchlist section is empty this run by
  construction, not a bug.
- **`big_move_lead_lag.py`, `earnings_lead_lag.py`** (both default `--tf 1h`): correctly aborted with
  "No confirmed pairs found for tf=1h" — neither confirmed pair is at 1h. This is the fix working as
  intended (no fabricated result for a timeframe with zero real confirmed pairs), not a failure; these
  will produce real output once run at `--tf 3m`/`--tf 4h` respectively.
- **`dd_hub_effective_bets.py`**: now dynamically finds "the largest hub in the current confirmed set"
  instead of the old fixed DD cluster (which no longer exists in the confirmed set at all). Correctly
  reported "No hub with >=2 confirmed pairs found (largest: 'KVUE' with 1) -- nothing to test" — with
  only 2 total confirmed pairs and no shared leg between them, there is structurally no hub to analyze
  right now. Honest null, not a bug.

13 of the 20 fixed scripts had not yet run in the pipeline's research sweep as of this entry; their
results will be added here as the pipeline (currently 88/195 stages complete) reaches them.

Files: `research/pair_source.py` (new), `debug/_verify_pair_source.py` (new, 6/6 pass), 20
`research/*.py` files fixed (see Development.md Session 32 continuation for the full file list),
fresh `output/research/{breakout_vs_reversion,breakout_vs_reversion_sweep,cross_timeframe_divergence_
deep,cross_timeframe_divergence_shallow,fdr_method_comparison_raw,fdr_method_comparison_summary,fdr_
method_comparison_known_pairs}*.parquet` (new, real runs on CachyOS).

**UPDATE, same day**: the "2 confirmed pairs" universe-thinness caveat that runs through this
entire finding is now STALE. `full_universe_eg_confirmation.py` (a separate full-universe EG+FDR
cascade, previously never wired into production) found 78 real candidates, and 27 survived a
real, multi-round data-integrity vetting (structural-pair/GVKEY-duplicate/WRDS-ticker-alias/
SPAC-NAV-clustering contamination all found and filtered — see Development.md's "78-pair
promotion" entry, same date, for the full account) before being promoted into
`output/results/1day/pairs.parquet` with full production enrichment. CAMARF's confirmed-pair
count as of this update: **29** (27 new @1D + the original `KVUE/KMB@3m` + `PNC/ZION@4h`), not 2
— every "thin confirmed set" disclaimer above this line describes the state BEFORE that
promotion, not the current one. Re-running the fixed scripts against the now-richer set is a real
follow-up, not yet done as of this update.

**UPDATE, 2026-09-01/02, a real gap found and closed**: this "29" figure was written on CachyOS
and never synced back to the Windows development machine. A full session's worth of new
comparison-arm work (below) initially ran locally against `pair_source.py::confirmed_pairs_list()`
reading an EMPTY local `output/results/1day/`, silently returning just the 1 pre-promotion pair
(`KVUE/KMB`) instead of the real 29 — not a regression in the promotion itself, a two-machine sync
gap that made local runs look like the project had stalled at n=1. Found via a downstream
comparison arm's own honest small-sample disclosure, traced to the root cause, and fixed by
syncing `output/results/{1day,4hr}/*.parquet` from CachyOS. Local reads now correctly return 29.
See `Development.md`'s 2026-09-01 entry and `docs/HANDOFF.md` for the full account — flagged here
too since this finding's own "29" claim is exactly what silently went stale.

## 40. Three Comparison-Arm Builds, Synthetic-Factory Extension, and a Contamination Investigation
[2026-09-01/02]

Per Ross's direct request to build out several open research questions, scoped individually
before building (per this session's own standing "scope then build" instruction), verified
synthetically before running on real data, then run for real:

**Sector-restricted FDR vs. a random-restriction null** (`research/sector_fdr_random_null_
comparison.py`) — motivated by an RQM-3 ("relational quantum mechanics," used only as a naming
analogy, see `docs/research/RQM_CONCEPTUAL_LENS_2026-09-01.md`) reading of
`sector_restricted_fdr_rescan.py`: does restricting the FDR candidate pool to same-GICS-sector
pairs change survivors because sector identity carries real signal, or just because shrinking m
via ANY same-sized restriction would? Verified via a known-ground-truth discrimination test (a
planted "real effect" subset correctly scores as an outlier against 500 random-restriction trials
for all 4 FDR methods) before trusting it on real data. **Real result: marginal.** Same-sector
restriction confirms 2 pairs vs. a random-null mean of ~1.1 survivors, landing at the 95.8th
percentile — right at the edge of "outside typical range," not a strong confirmation. At these
small integer counts the percentile math is coarse (1 vs. 2 survivors is a large percentile jump).

**Johansen basket cointegration vs. pairwise Engle-Granger** (`research/johansen_basket_
cointegration.py`) — does testing an already-confirmed pair plus a same-sector third leg as a
3-asset Johansen basket find genuine cointegration that pairwise EG, applied only to the untested
sub-pairs, misses entirely? A prior library survey wrongly attributed a Johansen test to the
`arch` package; verified directly it does not exist there (only pairwise Engle-Granger/
Phillips-Ouliaris) — the real implementation is `statsmodels.tsa.vector_ar.vecm.coint_johansen`,
already a CAMARF dependency. Verified synthetically (independent-walks null correctly shows rank
0; a genuine-shared-trend basket correctly shows rank≥1) before running for real. **First real run
(against the local, incomplete 1-pair confirmed set) found and fixed a real bug**:
`DataAligner.align_universe()`'s output dict is keyed by bare symbol name, not the `f"{sym}_{tf}"`
label used for its input — the original lookup silently skipped every triple before the overlap
check ever ran, an entirely different failure mode than "not enough data." **Re-run against the
real 29-pair confirmed set (after the sync fix above) found a genuine positive result**: the
`PNC/ZION/ABR` basket shows Johansen rank=1, and neither `PNC/ABR` nor `ZION/ABR` was ever
separately pairwise-confirmed — real basket cointegration detected that pairwise EG missed
entirely, exactly the "novel finding" case this comparison was built to surface. 1/6 triples
(16.7%) showed rank≥1 in this run; still a small sample (most of the 29 pairs' symbols aren't in
the Wikipedia-scraped GICS tag set at all, limiting same-sector third-leg matching), but a real,
positive, non-null result.

**CAMARF's hand-rolled DCC-GARCH vs. `pymgarch`** (`research/dcc_garch_pymgarch_comparison.py`) —
`stats.py` hand-rolls Engle (2002) two-step DCC on top of `arch`'s univariate GARCH(1,1) because
`arch.multivariate`'s own DCC class was removed in `arch` 7+. Verified `pymgarch` (PyPI 0.1.1) is
real, built on the same `arch>=7.0` marginals, with validated two-stage Engle-Sheppard standard
errors against R's `rmgarch` reference. **Clean, decisive result**: fit both on a synthetic panel
with a known correlation regime (baseline 0.15, crisis-window 0.75) — CAMARF's hand-rolled
implementation is validated as correct (RMSE vs. known truth: CAMARF 0.153 vs. pymgarch 0.167,
CAMARF marginally more accurate), the two independent implementations closely agree
(method-vs-method RMSE 0.031), and CAMARF's version is ~6.3x faster (2.67s vs. 16.91s on the same
panel). **Recommendation: keep the existing hand-rolled DCC, no reason to switch** — a rare "the
code was already right" finding, recorded precisely because most of this project's bug-hunting
finds the opposite.

**Data-contamination investigation into CAMARF's confirmed pairs — substantially resolved, one
real infrastructure gap found and fixed along the way.** `data_contamination_scan.py`'s
confirmed-pairs cross-check flagged all 10 unique symbols across CAMARF's production confirmed
pairs (`7267.T, 8058.T, EQR, INVH, IQV, KMB, KVUE, PNC, Q, ZION`) as having unexplained price
jumps. A targeted peer-corroboration follow-up (`research/confirmed_pairs_contamination_
followup.py`, reusing `peer_correlation_contamination_check.py`'s core logic) found most (639/746)
events were `likely_real_shared_event`, genuine unlabeled market moves, not contamination.
Re-checking the residual with GICS **sector-matched** peers instead of random ones corroborated
9 more, including `ZION` on 2023-03-13, the exact SVB/regional-bank-crisis date. **Separately, a
code-quality council review** found that `data_contamination_scan.py` itself only ever scanned the
yfinance-primary cache (`output/cache/`), never `output/cache/wrds/` — meaning this entire
investigation, as first run, never touched the WRDS-primary data CAMARF actually uses for these
symbols. Fixed (`list_price_cache_files()` now scans WRDS + Binance too, with a suffix-
normalization map since WRDS uses a completely different on-disk convention: `1D`/`1M`/`3M`/`6M`/
`7D`/`1Y` vs. yfinance's `1day`/`1mo`/`3mo`/`6mo`/`7day`); total scanned files jumped from 21,064
to 79,974. The corrected full re-scan (16,455s) still flags the same 10 symbols, now with
additional WRDS-only `1Y`-timeframe events included — **the new WRDS-scope events have not yet
been run through the peer-corroboration check**, so the "substantially resolved" conclusion from
the first pass is not yet re-verified against the corrected, full-coverage data. Net honest state:
likely still mostly real market events given the pattern already found, but the newly-surfaced
WRDS-only events are a genuine open item, not silently assumed clean.

**`debug/synthetic_pair_factory.py` extended** with 4 new factors covering the entire 2026-08
WRDS-merge/episodic-scan/PIT-safety arc this factory predates: `coint_regime_windows` (a genuine
time-varying cointegration schedule, replacing the single global bool), `symbol_a/b_membership_
spells` + `is_pit_member()` (the PIT S&P 500 membership gate), `adv_regime` + synthetic volume
generation (the ADV liquidity gate), and `make_duplicate_identity_pair()` (the SPAC/GVKEY/
ticker-collision contamination taxonomy). All additions verified bit-for-bit backward-compatible
with defaults omitted vs. explicit.

Files: `research/sector_fdr_random_null_comparison.py`, `research/johansen_basket_
cointegration.py`, `research/dcc_garch_pymgarch_comparison.py`, `research/confirmed_pairs_
contamination_followup.py` (all new), matching `debug/_verify_*.py` synthetic tests, `debug/
synthetic_pair_factory.py` (extended), `research/data_contamination_scan.py` (WRDS-coverage fix),
`debug/_verify_no_private_universe_globs.py` (new structural guard against the recurring
duplicated-universe-loader bug class, 13+ instances found across this project's history).

## 41. Tier 3's Real Episodic-Confirmed Count (929 of 7.8M Candidates), and the Real Cause of
94 Consecutive Crash-Restarts [2026-09-02]

The corrected-scale WRDS deep-history episodic scan (`research/wrds_deep_history_episodic_scan.py`)
finally finished, retiring the "still pending" status this number has carried since the
2026-08-24 universe fix. Final results: **Tier 1** (full-sample static EG) confirmed=1,404 of
894,733 candidate pairs; **Tier 2** (rolling-window EG, static-corr prefilter) episodic-confirmed=
875 of the same 894,733; **Tier 3** (rolling-window EG, rolling-corr prefilter — the broadest
candidate pool, deliberately not restricted to Tier 1's static-correlation survivors)
episodic-confirmed=**929 of 7,834,906 candidate pairs**.

Getting there required finding the real cause of a pattern that had been live for days:
94 consecutive crash-restarts on CachyOS, all attributed at the time to an unexplained "spin-up
memory spike" (see the entry immediately above this one in `Development.md`). That diagnosis was
wrong. Every one of the last several attempts died at the IDENTICAL point — right after the
rolling-EG checkpoint reported 100% done (7,834,906/7,834,906), before the final confirmed/windows
parquet files were ever written. Reading `run_rolling_eg_pool`'s own code found the real cause:
the 2026-08-26 streaming-checkpoint fix (documented in its own docstring) solved the mid-run
unbounded-accumulator problem, but never touched the END-of-run reconstruction step, which still
built THREE separate giant Python list/dict-of-dict copies of the same tens-of-millions-of-rows
checkpoint data simultaneously — a 2-3x peak, in the least memory-efficient possible
representation, at exactly the point that kept crashing. Rewrote it as a single vectorized pandas
merge (pivot "ab"/"ba" directions, take `max()`, explicit `gc.collect()` between intermediates).
Verified two ways before deploying: the existing checkpoint-resume test in `debug/_verify_wrds_
deep_history_episodic_scan.py` (all pass, identical results to an uninterrupted run), plus a
targeted byte-for-byte comparison of old-logic vs. new-logic output on a synthetic multi-part
checkpoint. Deployed; the run completed cleanly in 4.9 minutes on the first real attempt.

**Downstream, the same class of bug recurred immediately** in `research/crisis_regime_
correlation_diagnostic.py` (built earlier, gated on Tier 3 finishing) — `build_pair_level_table`
called a pandas boolean-filter-then-`.iloc[-1]` lookup (`_nearest_regime`) once per row inside a
Python-level `groupby` loop, ~5M individual calls against Tier 3's real 5,003,637-row windows
file. Not an OOM risk (CachyOS has ample RAM), but a real, and severe, wasted-time cost: killed
after 12+ minutes with no end in sight. Rewrote as a single vectorized `pd.merge_asof` (the
correct primitive for "most recent value on or before date"), verified byte-for-byte identical
output to the old logic on synthetic data (21.5x speedup at synthetic scale), redeployed — the
real 638,095-pair table now builds in under a minute total.

**The actual finding, now available (all three pre-registered sub-questions, with formal tests
for all three as of the 2026-09-02 re-run — the first pass reported reappearance rate and
confirmation strength as descriptive means only; both now have proper significance tests)**:

1. **Confirmation rate — significant.** Pairs whose FIRST qualifying rolling-correlation window
   fell in a crisis-VIX regime are episodically BH-FDR-confirmed at roughly **1.7x the rate** of
   calm-first pairs (0.248% vs. 0.146% of 11,715 vs. 281,654 candidate pairs respectively;
   two-proportion z=2.77, **p=0.0056**). Confirmation counts by first-qualifying regime (summing to
   the same 929 Tier 3 total, a real internal-consistency check): calm 412, normal 413, elevated
   75, crisis 29.
2. **Persistence (reappearance) — significant, and the largest effect of the three.** Crisis-first
   pairs reappear as a candidate in a later, different-regime window far more often than
   calm-first pairs (91.0% vs. 78.7%; two-proportion z=32.2, **p≈0**, driven by the large n) — this
   argues AGAINST the "transient, regime-driven artifact" reading of the original motivating
   observation (Ross's framing, verbatim, from the script's own docstring: "we have prior data
   showing stocks cointegrating or moving together more often during VIX crisis times"); a
   crisis-discovered pair is not merely a crisis-window fluke that vanishes once VIX normalizes,
   it is, if anything, MORE likely to persist as a candidate across regime changes.
3. **Confirmation strength — NOT significant, stated honestly rather than left as a bare
   descriptive mean.** Among confirmed pairs only, crisis-first pairs show a higher mean
   `episodic_fraction_fdr` (0.288 vs. 0.223 for calm), but a Mann-Whitney U test (the right choice
   for a bounded [0,1] fraction, not obviously normal) finds this difference is **not**
   statistically significant (U=5119, **p=0.196**) — almost certainly underpowered given only 29
   crisis-confirmed pairs vs. 412 calm-confirmed. This sub-question is reported as directional but
   inconclusive, not as a third confirmed effect alongside the first two.

**Non-monotonicity, disclosed directly rather than smoothed into a "more stress = more
confirmation" story**: the 4-way confirmation-rate table is NOT a clean calm→normal→elevated→
crisis gradient — elevated (0.140%) is actually slightly BELOW calm (0.146%) and normal (0.142%),
with only crisis (0.248%) standing out. This is a crisis-extreme effect specifically, not a
general dose-response relationship to market stress, and the script now flags this automatically
(`confirmation_rate_monotonic_across_regime_severity` in `summarize()`'s output) rather than
requiring a reader to notice it by inspecting the raw table. Absolute confirmation rates are tiny
in all four regimes (0.14%-0.25%) — this is the correlation-prefilter candidate pool (638,095
unique pairs), not a screened-down shortlist, so a low base rate is expected and not itself
informative; the regime-conditional DIFFERENCE is the finding, not the absolute level.

Files: `research/wrds_deep_history_episodic_scan.py` (fixed), `research/crisis_regime_
correlation_diagnostic.py` (fixed, then extended with the reappearance-rate/episodic_fraction_fdr
significance tests and the monotonicity check), `debug/_verify_crisis_regime_correlation_
diagnostic.py` (extended, 21/21 checks pass), `output/research/wrds_deep_history_episodic_scan_
tier3_{confirmed,windows}.parquet`, `output/research/crisis_regime_correlation_diagnostic_
{pairs,summary}.parquet`.

## 42. Adversarial Review of the Reframed Paper: the Crisis-Regime Confirmation-Rate Effect Is
Real But Concentrated in 2 of 12 Historical Episodes, Not a General Property [2026-09-02]

Per Ross's explicit request to "brutally dissect and bulletproof" the just-reframed
`PAPER_MAGNITUDE.md` (2-finding "discovery event" throughline, see Finding #41's HANDOFF.md
entry for the reframe itself), an adversarial-reviewer agent was dispatched to argue against the
paper's central claim and try to break it, not confirm it. It found several real, fixable
problems, the most serious of which changed what the paper's §5 finding actually is.

**The independence-assumption problem, confirmed real by direct measurement, not just flagged.**
The reviewer's core objection: `crisis_regime_correlation_diagnostic.py`'s two-proportion z-tests
treat each of the 11,715 crisis-first pairs as an independent Bernoulli trial, but crisis-VIX
periods cluster into a handful of real historical episodes, not thousands of independent draws
— so the pooled p-values likely overstate the effective evidence. Built and verified
`research/crisis_regime_episode_clustering_check.py` (`debug/_verify_crisis_regime_episode_
clustering_check.py`, 11/11 checks) to measure this directly rather than just disclose the risk:
groups crisis-first pairs into episodes via a fixed, disclosed rule (a new episode starts after
3+ consecutive months with no new crisis-first pair). **Real result: the 11,715 crisis-first
pairs are 12 distinct historical episodes, not 11,715 independent trials. Only 4 of the 12
episodes produced any confirmed pair, and the top 2 (2008-09 GFC, 2011 debt-ceiling/EU crisis)
carry 27 of 29 crisis confirmations (93.1%).** Notably, 2020 COVID — the other episode explicitly
named in the finding's own motivating observation — produced 2,329 crisis-first candidate pairs
but only 1 confirmation (0.04%), barely above the calm-period rate. **The confirmation-rate half
of Finding #41's crisis-regime result is real but substantially narrower than the pooled
p=0.0056 headline implied: a 2008-09-and-2011 effect specifically, not a general property of
crisis-VIX discovery conditions.** The reappearance/persistence half fares much better under the
same check — reappearance rate is consistently high (84%-100%, median 95.6%) across nearly every
episode except the two most recent (2024, 2025, where right-censoring — too little subsequent
history has elapsed to observe reappearance — is the likely explanation, not a weaker effect),
making persistence the more defensible of the two sub-findings, not confirmation rate.

**Other real fixes applied from the same review**: (1) two named, untested confounds added to
§5 — crisis-era factor/beta co-movement (cited: Forbes & Rigobon 2002, Longin & Solnik 2001,
neither previously cited despite §5 motivating itself with exactly this phenomenon) and
survivorship of crisis-discovered pairs into the current-constituent universe; (2) §4's "3 of 4
folds negative" framing was conflating two different failure modes — 2 folds found zero
PIT-confirmed pairs (inconclusive, not evidence of anything) while only 1 fold actually
demonstrated the causal-lookahead claim (a PIT-confirmed set that traded and lost money);
honestly restated as "1 of 4 folds is real supporting evidence, 2 inconclusive, 1 a thin
counter-example," not "3 of 4 negative"; (3) the paper's abstract/§1.4/§6 claimed §4 and §5 run
on "the same real, production-scale pipeline" — false for §4 specifically, which is still at the
1,576-symbol WRDS-primary universe, not the corrected ~44,700-symbol scale §5 uses; this scale
gap (already disclosed in §8, but not visible where the "same pipeline" claim was actually made)
is now stated directly everywhere that claim appears, and re-running §4 at corrected scale is
now explicitly the paper's top future-work item; (4) several instances of language stronger than
the evidence ("demonstrates," "neither depends on anything CAMARF-specific" stated as
established fact, editorializing like "the more surprising result") downgraded to defensible
claims; (5) "why one paper, not two" now explicitly states the §4/§5 connection is thematic, not
an empirically-tested interaction — the paper's own future-work section already conceded this
gap, so the synthesis text was overclaiming relative to its own disclosed limitations.

**What survived scrutiny, stated plainly, not to soften the above**: the reviewer independently
recomputed both z-statistics (2.77, 32.2) from the reported cell counts and confirmed them
arithmetically correct — nothing was fabricated or miscalculated, the problem was interpretive
(treating a clustered sample as independent), not computational. The disclosed limitations
already in the paper (non-monotonicity, the null confirmation-strength result, stale-scale
disclosures) were confirmed genuinely honest, not just claimed.

Files: `research/crisis_regime_episode_clustering_check.py` (new), `debug/_verify_crisis_regime_
episode_clustering_check.py` (new, 11/11 checks), `PAPER_MAGNITUDE.md` (Abstract, §1.4, §4, §5,
§6, §8, §10, References all updated), `output/research/crisis_regime_episode_clustering.parquet`.
Next: the 5-agent council review (council-quant-pm, council-academic-reviewer,
council-code-quality, council-process-meta, council-mfe-portfolio), run sequentially per this
project's standing rule, not yet dispatched as of this entry.

## 43. The Crisis-Regime Confirmation-Rate Finding Does Not Survive Cluster-Robust Testing;
Persistence Does, Marginally; the Episode Concentration Itself Is Statistically Real [2026-09-02]

After the 5-agent council review (Finding #42's continuation, see docs/HANDOFF.md), Ross asked
for a full follow-up analysis: resolve the "is the top-2-of-12-episode concentration itself just
chance" question quant-pm flagged as open, and run a proper independence/cluster-robust test on
the original crisis-vs-calm comparison rather than leaving episode-clustering as a disclosed risk.

**Two new verified scripts, both run for real:**

`research/crisis_regime_concentration_significance_test.py`
(`debug/_verify_crisis_regime_concentration_significance_test.py`, 7/7 checks) tests whether
27-of-29 confirmations landing in 2 of 12 episodes is more concentrated than each episode's
pair-count share would predict under a null where confirmation probability is constant per pair.
**Result: decisively real, not chance.** Exact binomial test: episodes 1+3 hold 54.1% of
crisis-first pairs, so ~15.7 of 29 confirmations would be expected there by chance; 27 were
observed (p=0.000006). 100,000-draw Monte Carlo of the same null: observed max-2-episode share
93.1% vs. null mean 59.4%, 95th percentile 72.4% (p=0.00002). Something genuinely unusual
happened in 2008-09 and 2011 specifically — not merely "these episodes happened to be large."

`research/crisis_regime_cluster_bootstrap_test.py`
(`debug/_verify_crisis_regime_cluster_bootstrap_test.py`, 7/7 checks) resamples the 12 crisis
episodes WITH REPLACEMENT (episode, not pair, as the resampling unit — the correct fix for
pooled-proportion tests on clustered data) to build a cluster-robust confidence interval for
each of the two significant sub-findings from Finding #41/#42. **Confirmation rate does NOT
survive**: cluster-robust 95% CI [0.022%, 0.398%] comfortably contains calm's observed 0.146%
rate (cluster-robust p-equivalent = 0.25, vs. the naive pooled z-test's p=0.0056). **Persistence
DOES survive, though far more weakly than the naive test suggested**: cluster-robust 95% CI
[77.5%, 96.3%], p-equivalent = 0.032 — still under the conventional 0.05 threshold, but an order
of magnitude weaker than the naive z=32.2/p≈0.

**The honest, resolved picture**: the episode concentration is real (statistically confirmed,
not a small-sample artifact), but that concentration is EXACTLY why the pooled confirmation-rate
test's independence assumption fails — 93% of signal coming from 2 of 12 units means there are
effectively only ~2 independent data points behind that claim, nowhere near enough for the naive
test's p=0.0056 to be trustworthy. Persistence, built from a pattern that replicates across
nearly all 12 episodes (not just 2), has real cluster-level support and survives, marginally.
`PAPER_MAGNITUDE.md` updated throughout (Abstract, §1.4, §5, §6, §8) to report the cluster-robust
numbers as the primary statistics, with the naive pooled tests explicitly labeled as
overstating confidence rather than presented as the headline result.

**Also this session**: confirmed the "27 vs 29" confirmed-pairs reconciliation directly against
real data rather than session memory — `output/results/{1day,4hr,3min}/pairs.parquet` hold
27+1+1=29 pairs exactly, no overlap, no error. Found (not yet acted on, needs Ross's WRDS-access
authorization) that `data_wrds.py` already has unexecuted survivorship-bias-mitigation
infrastructure (`get_delisted_sp500_permnos`, `build_delisted_label_map`) wired into
`universe_loader.py` (which globs its cache directory generically) — the delisted-symbol cache is
currently empty both locally and on CachyOS, meaning the code exists but has never actually run.

Files: `research/crisis_regime_concentration_significance_test.py` (new),
`research/crisis_regime_cluster_bootstrap_test.py` (new), both with matching `debug/_verify_*.py`
tests (7/7 each), `PAPER_MAGNITUDE.md` (Abstract/§1.4/§5/§6/§8 updated with cluster-robust
results as primary), `output/research/crisis_regime_concentration_significance.parquet`,
`output/research/crisis_regime_cluster_bootstrap.parquet`.

## 44. Full Brainstorm Execution Round: Gap-Rule Robustness, a Real (Inconclusive) Confound
Test, a Tested Null on Regime Strength, and a Real Discrepancy Found Re-Running §4 [2026-09-02]

Following the comprehensive weak/strong-point map, Ross authorized WRDS access (via the
already-configured `.pgpass`) and approved a broad brainstorm execution pass. Three new
verified scripts landed real results; a fourth in-progress script (re-running §4's PIT test)
surfaced a real discrepancy against the paper's existing numbers that needs resolution before
being trusted, reported here rather than silently accepted.

**Episode-clustering gap-rule sensitivity** (added to `crisis_regime_episode_clustering_check.py`):
the 3-month gap rule defining an "episode" was re-run at 1/2/4/6-month alternatives.
**Top-2-episode concentration share is identical (0.931) at every choice**; episode count only
varies mildly (11-13). The finding does not depend on the specific threshold, confirming it
wasn't tuned after seeing the result.

**Same-sector vs. cross-sector confound test** (`research/crisis_regime_same_sector_test.py`,
verified first, `debug/_verify_crisis_regime_same_sector_test.py`, 7/7 checks): tests whether
the persistence effect (§5) holds similarly for same-sector pairs (real economic co-movement
reason) and cross-sector pairs (would suggest pure common-factor co-movement if the effect
concentrates there). **A real methodological trap found and fixed on the first live run**: GICS
tags (S&P 1500 only, ~10% of Tier 3's pool) are a CURRENT-constituent snapshot, disproportionately
capturing recent discovery dates — 53% of GICS-tagged crisis-first pairs were from the 2 most
recent (right-censored) episodes, which flipped the entire result's direction until excluded.
After controlling for this (excluding 2024/2025 episodes, matching the main analysis's own
right-censoring treatment): **same-sector pairs show NO significant crisis effect (93.3% vs.
92.1% reappearance, n=75, p=0.69); cross-sector pairs show a real one (99.4% vs. 94.1%, n=359,
p=0.000018).** This pattern is consistent with, not against, the factor-co-movement confound
named in §5 — inconclusive (same-sector's null carries real power limits at n=75), but means the
confound cannot be dismissed as merely theoretical anymore.

**Regime-strength vs. discovery-regime test** (`research/regime_strength_vs_discovery_regime_
test.py`, verified first, `debug/_verify_regime_strength_vs_discovery_regime_test.py`, 8/8
checks): tests a third possible throughline connection — does a pair's cointegration-regime
STRENGTH (§7.2) correlate with its discovery regime? Across 56,003 jointly-covered pairs, a
chi-square test found no relationship (χ²=6.70, dof=6, p=0.349) — a real, tested null, reported
honestly rather than omitted. Discovery regime predicts persistence, not eventual strength.

**§4 re-run in progress on CachyOS, surfaced a real discrepancy, NOT yet resolved or reported
in the paper.** `research/pit_wfa_trade_bootstrap.py` (verified first, including a real bug
caught by the verify test itself before running on real data — an early design resampled raw
trades while keeping their original timestamps, which corrupted the daily-resample step the
Sharpe formula depends on; fixed by bootstrapping the already-aggregated daily P&L series
instead) re-derives the confirmed-pair set at `expanding/fold2_exp`'s cutoff live, to recover raw
trades for a bootstrap CI on the paper's existing 32-trade/−1.0121-Sharpe point estimate. **The
live re-run recovered 28 trades and a portfolio Sharpe of +0.3486 — different count, different
sign, from the paper's existing number.** Not yet explained: possibly the underlying cached 1h
universe data has changed since the original `pit_wfa_portfolio.parquet` run (new/removed
symbols in `output/cache`), possibly a real nondeterminism in the screening step. This needs
investigation before treating the bootstrap CI (or the original point estimate) as reliable —
explicitly not papered over. `rolling/fold2_roll`'s re-run still in progress as of this entry.

**Also this session, authorized by Ross**: the historically-delisted S&P 500 survivorship-bias
fetch (`data_wrds.py --only-delisted-sp500`, infrastructure found unexecuted in Finding #43) was
launched live against real WRDS data via the pre-configured `.pgpass` — 1,340 delisted permnos
identified, fetch in progress as of this entry, not yet joined back into any analysis.

Files: `research/crisis_regime_same_sector_test.py` (new), `research/regime_strength_vs_
discovery_regime_test.py` (new), `research/pit_wfa_trade_bootstrap.py` (new, in progress),
matching `debug/_verify_*.py` tests (7/7, 8/8, 6/6), `research/crisis_regime_episode_clustering_
check.py` (extended with gap-rule sensitivity), `PAPER_MAGNITUDE.md` (§5 confounds/robustness
section substantially expanded). Not yet done: resolve the trade-count/Sharpe-sign discrepancy;
join the delisted-securities fetch into the survivorship confound analysis once complete.

**UPDATE [2026-09-02, same day]: both jobs completed, §4's discrepancy resolved (as a disclosed
limitation, not a bug fix), delisted fetch confirmed picked up automatically.**

`pit_wfa_trade_bootstrap.py`'s `rolling/fold2_roll` re-run finished with an even larger
divergence than `expanding/fold2_exp`'s: **49 PIT-confirmed pairs now vs. 1 originally**, 288
trades at Sharpe −0.4548 vs. the original's 5 trades at +0.2547. Investigated rather than
accepted at face value: cached universe size is nearly unchanged (1,576 at the original run vs.
1,579-1,580 today) and the fold's actual cutoff dates are nearly identical (within about a week
— ruling out both universe growth and the minor calendar-window drift `pit_wfa.py`'s percentage-
based fold computation is subject to as the primary cause); the re-run script's call to the
shared screening function was checked line-for-line against production `run_fold`'s and matches
exactly, ruling out a bug in the re-derivation itself. **Most likely explanation, not fully
isolated to a specific commit**: the shared screening pipeline (`analysis.py`/`Config`) has
itself changed in the ~3 weeks between the original run and this session's re-run — this project
has had substantial, ongoing development on exactly those shared components in that window.
**Resolution**: §4's original table is kept as reported (a historically-dated result, not a
fixed, on-demand-reproducible fact), with this reproducibility gap now disclosed directly in
`PAPER_MAGNITUDE.md` §4/§8 rather than silently assumed away. Separately, caught and fixed a
real factual error already sitting in the paper's own §8 disclosure: it claimed `pit_wfa.py`
draws its screening universe from `universe_loader.load_full_universe()`; reading the actual code
confirmed it globs `output/cache/*_1hr.parquet` directly, bypassing that loader entirely — an
inaccurate claim written earlier in this session, now corrected to match the verified code.

`data_wrds.py --only-delisted-sp500` completed cleanly: **1,340/1,340 delisted S&P 500 symbols
fetched (daily+monthly+derived timeframes), zero failures, 28.0 minutes total.** Confirmed the
new files are picked up automatically by `universe_loader.load_full_universe()` (glob-based, no
code change needed): daily-scale merged universe grew from ~44,700 to **44,840** symbols.
**Not yet joined into any specific analysis** (§5's crisis-regime scan or §7.2's episodic
segmentation would both need a substantial re-run to actually benefit from this — flagged for
Ross's scoping decision, not done unilaterally given the scale).

Files (this update): `output/cache/wrds/PERMNO*_1D.parquet` etc. (1,340 new delisted-symbol
files), `PAPER_MAGNITUDE.md` (§4/§8 reproducibility disclosure + factual-error correction).

## 45. Phase 1 + 1b of the Discovery-Event Research Program: 53,118 Correlation Transitions
Catalogued, a Continuous Cointegration-Strength Series Built (Vectorized Twice, Live) [2026-09-03]

Ross scoped a new research direction, clarified over several exchanges: (1) redesign §4's PIT
test onto WRDS daily bars at full scale (not yet built, scoped only); (2) apply capital
constraints and risk-management-style sizing to trade measurement (scoped, reuses `portfolio_
sim.py`'s existing `replay_portfolio`, not yet wired in); (3) build the residual-correlation
factor-adjustment confound test (scoped, not yet built); (4) a combined research program on
"no-correlation as a signal" and "combining correlated with uncorrelated," clarified via
AskUserQuestion as: extend the existing `decoupling_analysis.py`/`decoupling_requalification.py`/
`decoupling_backtest.py` chain, run a properly-scoped meta-analysis of related null results, build
a diversification-basket signal, generalize decoupling into full correlation-regime TRANSITIONS
(both directions), and blend correlated-pair trades with uncorrelated-asset hedging — all via
with/without comparison arms to find optimal parameters, not a single fixed design (Ross: "it's
meant to be for comparison first with and without... to figure out optimal figures").

**Phase 1 built and run**: `research/correlation_transition_detector.py`
(`debug/_verify_correlation_transition_detector.py`, 11/11 checks) generalizes §7.2's existing
binary coint/not_coint span segmentation into a full transition catalog — every `coint→not_coint`
(decoupling, already partially studied by the existing decoupling_* chain) AND `not_coint→coint`
(recoupling, not previously catalogued anywhere in this project) boundary, each regime-tagged
point-in-time-safe via the same `merge_asof` machinery `crisis_regime_correlation_diagnostic.py`
already uses. **Real result: 53,118 transitions across the full Tier 3 universe (37,301
decoupling, 15,817 recoupling)**, broken out by VIX regime — crisis regime shows the FEWEST
transitions of any regime bucket (966 decoupling + 321 recoupling), consistent with earlier
session findings that crisis-discovered pairs are unusually persistent, not more volatile.
**A real anti-pattern caught and fixed live, before it finished running**: the first version used
a Python-level loop over 638,095 pair-groups (the same class of bug fixed twice earlier this
session) — killed after 2+ minutes with no sign of completing, rewritten with vectorized
`groupby(...).shift(1)`, re-verified identical on the same 11 checks, reran in 6.3 seconds.

**Phase 1b built and run**: `research/coint_strength_series_builder.py`
(`debug/_verify_coint_strength_series_builder.py`, 10/10 checks, including a real performance
proxy check at many-small-groups scale — proactively testing for the exact anti-pattern class
that bit Phase 1, not just correctness) converts Tier 3's raw per-window EG p-values into a
CONTINUOUS cointegration-strength series per pair (`coint_strength = 1 - pvalue`), plus a causal
rolling z-score and a decay-rate (window-over-window first difference) — the literal "coint %
treated like a price bar" Ross asked for, with entry/exit-style signal construction (Phase 2b,
not yet built) as the next step. **Real result**: 5,003,637 rows scored in 1m50s; only 1,063,771
(~21%) get a valid z-score at the current `z_window=10` default, since most pairs only have ~7-8
windows total — a real, honest signal the window parameter needs tuning via the with/without
comparison-arm plan, not a fixed guess (already disclosed in the script's own docstring before
this was even run). The Python function itself avoided the anti-pattern proactively this time
(built-in `GroupBy.rolling()`/`GroupBy.diff()`, not `.transform(lambda ...)`, which — checked and
confirmed via the verify suite's own performance check — would have been just as slow as Phase
1's first, killed attempt).

**Not yet built**: Phase 2 (does a transition's type/regime context or the continuous
coint-decay-rate predict anything, tested via with/without comparison arms sweeping candidate
z_window/threshold values) and Phase 2b (a coint-% "bar" system with entry/exit rules mirroring
price-bar convention) — these are the natural next steps and depend on Phase 1/1b's real output,
now available. §4's WRDS-daily-bars redesign, capital-constrained/risk-managed trade measurement,
and the residual-correlation factor test remain scoped but unbuilt, independent threads.

Files: `research/correlation_transition_detector.py` (new, vectorized), `research/coint_
strength_series_builder.py` (new), matching `debug/_verify_*.py` tests (11/11, 10/10),
`output/research/correlation_transitions.parquet`, `output/research/coint_strength_series.parquet`.

## 46. Residual-Correlation Factor Test Completed — The Crisis-Regime Reappearance Gap Survives
Factor-Adjustment Even in Pairs Whose Raw Correlation Is Genuinely Not Factor-Driven [2026-09-03]

Real production bug found and fixed first: `research/pit_wfa_wrds_daily.py --variant expanding`
crashed on its first full-scale run (`TypeError: float() argument must be a string or a real
number, not 'NoneType'` at `backtest.py:484`). Root cause: `pair_row.get("hurst_rs", np.nan)`
only falls back to the default when the KEY is absent from the Series, not when the key is
present with value `None` — and the underlying Hurst R/S estimate can genuinely return `None`
(insufficient data), which survives into `pair_row` because `pit_wfa_wrds_daily.py:260` sets the
key explicitly via `getattr(pair_result, "hurst_rs", np.nan)`. `pit_wfa.py`'s own 1h path never
hit this in three weeks of runs (more bars per pair, so the Hurst estimate reliably succeeds),
but the bug lives in the shared `BacktestEngine.run()`, not either caller — fixed there once, for
both. `debug/_verify_backtest_hurst_none_fix.py` (new) reproduces the exact scenario; the first
draft of the test used a strings+None-only dict and did NOT reproduce the crash, because pandas
silently normalizes `None` to `NaN` on a pure-object/str-inferred Series — only a dict mixing
floats, strings, AND `None` (matching the real `pair_row`'s shape) forces the `object` dtype that
lets a real `None` survive `.get()`. Fixed, verified locally and on CachyOS, relaunched.

**`research/residual_correlation_factor_test.py` completed** (the decisive version of the
same-sector-proxy confound test from Finding #44 — does crisis-regime reappearance persistence
survive once each symbol's return series is regressed against SPY and only the OLS residual is
used for correlation, directly testing the Forbes & Rigobon 2002 / Longin & Solnik 2001 "crisis
correlation is a market-factor artifact" confound). Real result, 638,095 candidate pairs, 5,700
unique symbols each residualized once (not once per pair):

- 42,715 of 638,095 pairs (6.7%) still clear `|residual correlation| >= 0.4` after the shared
  SPY factor is regressed out — genuine, non-factor-driven co-movement.
- **Survives residual correlation** (n_crisis=1,559, n_calm=14,555): crisis reappearance 88.26%
  vs. calm 78.41%, z=9.13, p≈0. The gap is real even in pairs whose correlation is NOT explained
  by the shared market factor.
- **Factor-explained only** (n_crisis=10,156, n_calm=267,099): crisis reappearance 91.42% vs.
  calm 78.67%, z=31.05, p≈0. The gap is present here too, and larger — most of the crisis-regime
  reappearance signal actually lives in the factor-driven subset, not the residual-surviving one.

Read plainly: the crisis-regime reappearance effect is not purely a Forbes-Rigobon /
factor-co-movement artifact — a real, if smaller, gap survives in pairs whose correlation
residualizes away from the market factor. But most of the raw effect (by pair count and by z)
sits in the factor-explained group, meaning the confound is real too, just not total. This
sharpens, rather than resolves, Finding #44's inconclusive same-sector proxy result into a
decisive split.

**Caveat carried forward from Finding #43, not yet re-applied here**: both z-tests above are
naive pooled pair-level tests, the same kind of test that Finding #43's cluster-robust episode
bootstrap showed overstates significance for the *confirmation-rate* claim specifically — the
*reappearance-rate* claim (this test's metric) was the one that WEAKLY survived cluster-robust
testing (p=0.032, not p≈0). This test's z≈9-31 numbers should be read as evidence the effect
exists and splits the way described above, not as literal p-values — a cluster-robust rerun
(episode-level resampling, same method as Finding #43) on both subgroups is the natural next
step before this goes in `PAPER_MAGNITUDE.md` §5 as anything stronger than a preliminary split.

Files: `research/residual_correlation_factor_test.py`, `backtest.py` (hurst_rs fix),
`debug/_verify_residual_correlation_factor_test.py` (15/15), `debug/_verify_backtest_hurst_none_fix.py`
(new, 4/4), `output/research/residual_correlation_factor_test.parquet`.

## 47. Real Systemic Bug: `portfolio_sim.py` Silently Skipped Every Capital-Constrained Trade for
WRDS-Daily Pairs (0/21 Taken, Deterministic Across Relaunches) [2026-09-03]

`pit_wfa_wrds_daily.py`'s fold1 capital-constrained result (`flat_2pct`, $100k account) showed
0/21 trades taken with Sharpe/max_dd/profit_factor/PDR all NaN — reproduced byte-identically
across two independent relaunches, ruling out a flaky/nondeterministic cause and pointing at a
real, systemic wiring bug rather than a thin-1925-1946-fold data artifact. Root cause traced to
`portfolio_sim.py`'s `get_price_at()` and `_load_spread_series()`: both hardcode reads from disk
(`output/cache/{symbol}_1hr.parquet`, `output/results/{tf}/spread_series_{a}_{b}.parquet`) —
files `pit_wfa.py`'s own 1h pipeline writes, but which `pit_wfa_wrds_daily.py`'s WRDS-daily pairs
never produce, since it works entirely in-memory
(`universe_loader.load_full_universe()`, no per-pair `spread_series_*.parquet` output for
`_TF_LABEL="1D"` anywhere in the codebase). Both functions silently returned NaN for every
WRDS-daily symbol/pair, which cascaded through `stop_distance_dollars_per_share()` (also NaN) and
made every trade fail the `flat_2pct`/Kelly-sizing risk-estimate check — the exact
`n_skipped_no_risk_estimate` path, not a genuine zero-edge finding.

**Fixed via an injectable in-memory override**, not a rewrite of the file-based path: added
`portfolio_sim.register_price_series(symbol, df)` / `register_spread_series(symbol_a, symbol_b,
tf_label, df)` / `clear_external_series()`, checked FIRST in `get_price_at()`/
`_load_spread_series()` before falling through to the existing file-based cache — `pit_wfa.py`'s
own behavior (never calls these) is byte-identical to before this change. `pit_wfa_wrds_daily.py`
now registers each pair's already-in-memory aligned close-price series and spread series inside
`backtest_pair_on_test_window()` (the full train_start..test_end window, not just the test slice,
so causal rolling-std has enough trailing history right at test_start). Verified with a new
synthetic test (`debug/_verify_portfolio_sim_external_series_fix.py`, 7/7 checks, including an
explicit "no accidental global leakage" check confirming an unregistered pair still correctly
returns NaN after a different pair is registered) plus the existing `debug/_verify_pit_wfa_wrds_
daily.py` suite (15/15, unaffected). Synced to CachyOS, re-verified there, relaunched as
`logs/pit_wfa_wrds_daily_20260903_v6.log`.

**Post-fix real result on fold1_exp: still 0/21 trades taken — confirmed, via a direct synthetic
reproduction (`notional_at_entry`/`stop_distance_dollars_per_share` probed manually with the same
functions the real replay uses), that this is now a genuine capital-scale finding, not the wiring
bug.** The wiring fix demonstrably works: `notional_at_entry` resolves real prices via the
registered series (confirmed directly, non-NaN, non-zero). What remains is two already-documented,
disclosed mechanics interacting: (1) trades entering with `|entry_z| >= STOP_ZSCORE` (3.5) get a
correctly-NaN risk estimate by design (the module's own long-standing ~45%-of-trades property);
(2) a trade that DOES get a valid, finite risk-per-share estimate can still demand a position size
far larger than the account can fund — flat_2pct sizing has no built-in cap on how large that
demand can get, and this run passes `--concentration-cap` as its default of `None`, so nothing
shrinks `target_notional` before the `available capital / target_notional < min_size_scale (5%)`
floor rejects it outright rather than partially funding it.

**Not a bug to silently fix by picking new default numbers**: `pit_wfa.py`'s original, already-
cited 1h run never called `portfolio_sim.replay_portfolio()` at all (confirmed via direct grep —
zero matches) — there is no existing $100k-account/no-concentration-cap precedent from the cited
baseline to match parameters against. This capital-constrained overlay is new work this session
built from scratch per Ross's request ("for the trades make sure capital constraints also apply,
and measure using per risk management optimization style"), so choosing an account size and
concentration cap that produce a MEANINGFUL (non-degenerate) capital-constrained result is a real
methodological choice, not a parameter default to silently guess at — flagged to Ross rather than
picked unilaterally. The `--variant expanding` run is left running as-is; its real (possibly still
0-trade) numbers for later folds will be reported honestly, not overwritten by an untested
parameter change.

Files: `portfolio_sim.py` (register_price_series/register_spread_series/clear_external_series,
get_price_at/_load_spread_series check the override first), `research/pit_wfa_wrds_daily.py`
(registers in `backtest_pair_on_test_window`), `debug/_verify_portfolio_sim_external_series_fix.py`
(new, 7/7).

**Resolved, real result confirmed on the live full-scale run**: Ross was asked
(`--concentration-cap` default: cap vs. raise account size vs. report 0-trades honestly vs.
switch sizing method) and chose to add a concentration cap. `--concentration-cap` now defaults to
`Config.BACKTEST.MAX_CONCENTRATION_PCT` (0.20 — this project's own already-declared, previously
never-enforced constant, reused rather than a newly-invented number). Relaunched as
`logs/pit_wfa_wrds_daily_20260903_v7.log`: fold1_exp's capital-constrained line now reads
**11/21 trades taken, Sharpe=-0.4779, max_dd=0.22%, profit_factor=0.2311, PDR=105.2074** — real,
finite numbers, confirming both fixes (the wiring bug and the concentration cap) work end-to-end
on the actual production run, not just the synthetic reproduction. Run continuing through the
remaining `expanding` folds as of this entry.

## 48. `pit_wfa_wrds_daily.py --variant expanding` Completed — Real, Mixed-Sign Capital-Constrained
Result Across Both Folds [2026-09-03]

The `expanding` variant completed cleanly in 69.7 minutes (`logs/pit_wfa_wrds_daily_20260903_v7.log`)
— by design only 2 folds (`fold1_exp`, `fold2_exp`, matching `pit_wfa.py`'s own long-standing
`FOLD_EXPANDING` definition, not a truncation). Real, non-degenerate capital-constrained
(`flat_2pct`, $100,000 account, `concentration_cap=0.20`) results for both:

| fold | pairs confirmed | raw trades | raw Sharpe | capital-constrained trades taken | CC Sharpe | max_dd | profit_factor | PDR |
|---|---|---|---|---|---|---|---|---|
| fold1_exp | 31 | 21 | -0.7920 | 11/21 | -0.4779 | 0.22% | 0.2311 | 105.21 |
| fold2_exp | 110 | 50 | 0.1571 | 25/50 | 0.1918 | 0.57% | 1.9057 | 333.28 |

**Read honestly, not spun as a clean win**: the two folds disagree in sign (fold1 negative,
fold2 positive, both raw and capital-constrained) — this is not yet a stable, one-direction edge
across the `expanding` variant's own two folds, the same kind of fold-to-fold instability §4's
original 1h result already showed. Capital-constraint take-rate is roughly half in both folds
(11/21, 25/50) — the concentration cap is doing real, active work, not merely a formality.
**No single pooled-across-folds headline number is reported here**: `pit_wfa_wrds_daily.py`
persists only per-fold summary rows (`pit_wfa_wrds_daily_capital_sim.parquet`, confirmed directly
— no aggregate row exists), and computing a genuine single portfolio-level Sharpe across both
folds would need their equity curves stitched chronologically (the two folds' test windows are
different eras — fold1 spans an analysis window inside [1925-12-31, 1976-04-22], fold2 spans
into [1976-04-22, ...]), not a naive average of two already-annualized Sharpe ratios. Flagged as
the natural next step, not fabricated here.

Files: `output/backtest/pit_wfa_wrds_daily_{fold_comparison,portfolio,pair_sets,capital_sim}.parquet`.
Next: `--variant rolling` (same concentration-cap default, no extra flags needed).

**Update: `--variant rolling` also completed** (103.0 min, `logs/pit_wfa_wrds_daily_rolling_
20260904_v1.log`). `fold1_roll` matches `fold1_exp` exactly (11/21 trades, Sharpe=-0.4779) — by
design, both variants share fold1's date range (`FOLD_EXPANDING`/`FOLD_ROLLING` both start with
`(0.00, 0.20, 0.20, 0.50)`). `fold2_roll` is the most statistically substantive fold of either
variant by a wide margin — its test window runs [1996-06-05, 2025-12-31], 303 confirmed pairs, 39
traded, **1,533 raw trades** (raw portfolio Sharpe -0.2589). Capital-constrained (`flat_2pct`,
$100k account, 0.20 concentration cap): **309/1,533 trades taken, Sharpe=+0.2175, max_dd=5.50%,
profit_factor=1.7830, PDR=32.44.** Notable and worth flagging plainly: the concentration cap
doesn't just filter trades here, it flips the portfolio Sharpe's SIGN (-0.26 raw → +0.22
constrained) — consistent with the cap doing real downside-risk reduction (capping exposure to
the largest, worst-performing positions) rather than merely shrinking scale. This is the single
largest and most substantive real capital-constrained result produced by this comparison arm so
far and the best current candidate for what a future paper section would cite, though it is one
fold, not yet a robustness-checked headline (no cluster-robust or bootstrap CI computed on it,
same caveat class as Finding #43/#46).

**This completes Ross's full 3-item sequence** (WRDS daily bars → capital-constrained/
risk-managed trade measurement → residual-correlation factor test — Finding #46 covered the
third item already). All three real, disclosed results now exist: §4's causal-validity test now
has a genuine full-scale WRDS-daily comparison arm (mixed-sign across 3 of 4 total folds, one
strongly positive), the capital-constrained overlay is wired correctly end-to-end (two real bugs
found and fixed along the way, Findings #46-47), and the crisis-regime persistence effect is now
known to be partly-but-not-purely a market-factor artifact (Finding #46).

**Real data-loss bug found and fixed, same day**: the overwrite described above (expanding's
parquet destroyed by rolling's run) was a genuine bug, not accepted as a permanent limitation —
`main()` wrote all 4 output parquet files under fixed filenames with no `--variant` suffix, so a
second invocation with a different `--variant` silently destroyed the first's saved output
entirely (nothing was actually lost this time only because the real numbers were manually
recovered from the log files before this was noticed). Fixed via `_merge_and_save()`: reads the
existing parquet if present, drops any rows matching the new run's `(wfa_variant, fold)` keys,
and concatenates — a different variant's rows are now preserved, while re-running the SAME
variant still correctly replaces only its own prior rows (no duplication). Verified with a new
synthetic test (`debug/_verify_pit_wfa_wrds_daily_merge_and_save.py`, 7/7) plus the existing
15/15 suite, unaffected; synced and re-verified on CachyOS.

Files (this update): `research/pit_wfa_wrds_daily.py` (`_merge_and_save` fix),
`debug/_verify_pit_wfa_wrds_daily_merge_and_save.py` (new, 7/7),
`output/backtest/pit_wfa_wrds_daily_{fold_comparison,portfolio,pair_sets,capital_sim}.parquet`
(currently hold only the rolling-variant rows, since the fix landed after the overwrite already
happened this run — future re-runs of either variant will correctly accumulate both).

## 49. Phase 2 of the Discovery-Event Research Program: `coint_strength_z` and `coint_decay_rate`
Both Predict Next-Window Cointegration Persistence, Strongly and Consistently [2026-09-04]

`research/coint_decay_rate_signal_test.py` (verified first, `debug/_verify_coint_decay_rate_
signal_test.py`, 13/13 checks) tests whether Phase 1b's continuous cointegration-strength
trajectory predicts anything, per Ross's "coint % treated like a price bar" framing and his
explicit with/without comparison-arm instruction. Two predictors tested against the same outcome
(does the pair's NEXT rolling window still have p-value < 0.05, i.e. remain "coint"): the causal
rolling z-score of `coint_strength` (swept across `z_window` ∈ {5, 10, 15, 20} × `threshold` ∈
{1.0, 1.5, 2.0}, 12 combinations) and `coint_decay_rate`'s sign. "WITH signal" is always compared
against the true population baseline (every row with a defined outcome), not a hand-picked
comparison group.

**Real result, run against the full 5,003,637-row `coint_strength_series.parquet`
(4,365,542 rows with a defined next-window outcome): both predictors show a strong, highly
significant, and directionally sensible relationship, consistently across every parameter
choice tested.**

Elevated `coint_strength_z` predicts materially higher persistence at every one of the 11
combinations that had qualifying rows (12th, `z_window=5`/`threshold=2.0`, had zero rows — a
small window rarely reaches that extreme a z-score, not a bug):

| z_window | threshold | n_signal | persist rate | baseline rate | ratio | z-stat |
|---|---|---|---|---|---|---|
| 5 | 1.0 | 675,695 | 8.17% | 4.74% | 1.7x | 116.2 |
| 5 | 1.5 | 180,903 | 6.72% | 4.74% | 1.4x | 38.3 |
| 10 | 1.0 | 484,044 | 9.91% | 4.16% | 2.4x | 165.8 |
| 10 | 1.5 | 206,397 | 8.87% | 4.16% | 2.1x | 98.9 |
| 10 | 2.0 | 46,589 | 8.34% | 4.16% | 2.0x | 44.4 |
| 15 | 1.0 | 331,147 | 10.25% | 3.83% | 2.7x | 156.8 |
| 15 | 1.5 | 144,282 | 9.52% | 3.83% | 2.5x | 102.6 |
| 15 | 2.0 | 43,994 | 9.01% | 3.83% | 2.4x | 55.0 |
| 20 | 1.0 | 155,023 | 10.07% | 3.36% | 3.0x | 117.4 |
| 20 | 1.5 | 67,581 | 9.96% | 3.36% | 3.0x | 85.4 |
| 20 | 2.0 | 22,280 | 9.46% | 3.36% | 2.8x | 48.8 |

All p≈0. `coint_decay_rate < 0` (a weakening cointegration-strength trend) shows the mirror
relationship, and it makes economic sense directionally: it predicts LOWER next-window
persistence (2.85% vs. baseline 4.76%, z=-107.6, p≈0) — a pair whose cointegration is actively
decaying is more likely to break down next period, not less.

**Two honest caveats, not silently absorbed into the headline.** First, the SAME cluster-
robustness concern Finding #43 raised for the crisis-regime pooled z-tests applies here just as
directly: these are naive pooled two-proportion z-tests treating each (pair, window) row as an
independent trial, but many rows come from the SAME 638,095 pairs (multiple windows per pair,
sequentially dependent by construction — a persistent pair contributes many rows, an
episodically-confirmed one contributes few). The z-statistics here (44-166) are large enough that
even a substantial clustering correction is unlikely to erase significance entirely (Finding
#43's own confirmation-rate effect, by contrast, had z≈5-6 pooled and did not survive), but a
cluster-robust rerun (episode- or pair-level resampling, same method as Finding #43/#46) is the
right next check before this goes into `PAPER_MAGNITUDE.md` as a headline claim, not assumed
robust by z-statistic size alone. Second, the "baseline" population differs across `z_window`
choices (only rows with a DEFINED z-score at that window size are included, and larger windows
have fewer valid rows — the same ~21%-at-`z_window=10` coverage gap already disclosed in Finding
#45), so the ratio column above should be read as "signal vs. that window's own valid
population," not as a fully controlled comparison across window sizes — each individual row of
the table is internally valid, the table is not evidence that z_window=20 is "better" than
z_window=5 in some window-invariant sense.

Files: `research/coint_decay_rate_signal_test.py` (new), `debug/_verify_coint_decay_rate_
signal_test.py` (new, 13/13), `output/research/coint_decay_rate_signal_test.parquet`. Next:
Phase 2b (a coint-% "bar" system with entry/exit rules mirroring price-bar convention, building
directly on this confirmed signal).

## 50. Phase 2b: a Coint-% "Bar" System — Real, But `decay_rate<0` Dominates as the Exit Trigger
Regardless of the z-Reversion Threshold Chosen [2026-09-04]

`research/coint_strength_bar_system.py` (verified first, `debug/_verify_coint_strength_bar_
system.py`, 15/15 — including a real bug the verify test caught: `exited_at_series_end` compared
a numpy `bool_` to Python's `False` singleton via `is`, which never matches even when true/equal;
fixed to `not exited`) mirrors this project's own existing price-bar `ENTRY_ZSCORE`/`EXIT_ZSCORE`
convention, inverted in spirit since a HIGH `coint_strength_z` is the desirable state here (per
Finding #49): entry = first window where `coint_strength_z` (fixed at `z_window=20`, Finding
#49's strongest observed ratio) crosses above `entry_threshold`; exit = the first SUBSEQUENT
window where EITHER `coint_strength_z` reverts below `exit_threshold` OR `coint_decay_rate` turns
negative, mirroring price-bar's own dual `EXIT_ZSCORE`/`STOP_ZSCORE` exit convention. Swept per
Ross's with/without instruction across `entry_threshold` ∈ {1.0, 1.5, 2.0} × `exit_threshold` ∈
{0.0, 0.5, 1.0}, matching `config.py`'s own `COARSE_ENTRY_ZSCORE`/`COARSE_EXIT_ZSCORE` sweep
style.

**A real performance bug caught proactively, before it was ever run at full scale**: the first
implementation looped via `df.groupby(["symbol_a", "symbol_b"])` (638,095 pairs) with a small
inner Python loop per pair — timed on just a 5,000-pair subset and still hadn't finished after
2+ minutes, the same anti-pattern class already fixed twice earlier this session. Rewritten as a
single flat pass over plain numpy arrays sorted by (pair, window), with group-boundary resets
instead of per-group pandas iteration; the full 5,003,637-row run then took **7.9 seconds** for
one threshold combo, all 9 combos in under 3 minutes total.

**Real result on the full dataset.** Entry threshold materially changes how many bars form (from
122,051 bars/96,546 pairs at `entry=1.0` down to 22,555 bars/21,404 pairs at `entry=2.0`, as
expected — a stricter entry bar is rarer), but bar LENGTH and in-bar persistence are remarkably
stable across every entry level (mean length ≈2.09 windows, median 2.0; in-bar persist rate
10.4%-11.1% vs. the unconditional baseline 5.13% — roughly 2x, consistent in direction with
Finding #49's per-window test though numerically a coarser aggregate, since this averages
persistence across the whole bar including its own entry window). **The exit-threshold sweep is
essentially inert**: bar counts, lengths, and persist rates are nearly identical across
`exit_threshold` ∈ {0.0, 0.5, 1.0} for any fixed entry level — because `coint_decay_rate<0`
dominates as the actual exit trigger in practice (73.5%-77.2% of exits attributed to decay vs.
14.4%-51.0% to z-reversion, not mutually exclusive when both fire the same window), meaning the
z-reversion half of the mirrored price-bar convention rarely gets to fire first. Also disclosed
directly, not silently absorbed: 22.8%-26.1% of bars are still open at their pair's series end
(right-censored by Tier 3's own data-build cutoff, not a system failure to exit).

**Read honestly**: this Phase 2b bar system is real and internally consistent with Phase 2's
underlying signal, but the "bar" framing itself doesn't add information beyond what Finding #49
already established — the exit rule that actually matters is decay-rate-based, not the
z-reversion half explicitly modeled on price-bar convention, and bar duration is short and
essentially fixed regardless of entry strictness. The natural implication for a future trading
system built on this: a simpler decay-rate-only exit rule would likely perform identically to the
full dual-condition system at a fraction of the complexity — not yet tested directly, flagged as
the natural next check if this signal is pursued further.

Files: `research/coint_strength_bar_system.py` (new), `debug/_verify_coint_strength_bar_
system.py` (new, 15/15), `output/research/coint_strength_bar_system.parquet`.

## 51. Real Bug in `backtest.py:compute_metrics()`'s Sharpe Annualization — Isolated to Per-Pair
Diagnostic Tables After a Full Audit; No Cited Headline Number Was Ever Affected [2026-09-04]

While scoping Phase 3 (a meta-analysis of `decoupling_requalification.py`/`decoupling_
backtest.py`'s real results, per Ross's earlier scoping), `output/research/decoupling_
backtest.parquet` showed Sharpe ratios of **-279.58** and **-590.15** for two 1m/2m-timeframe
pairs — nothing else in this project reports anything close to that magnitude. Investigated
before building anything on top of it, per this project's own "distrust surprising numbers, ask
for raw evidence" discipline.

**Root cause**: `backtest.py:compute_metrics()` annualized per-TRADE P&L using
`sqrt(bars_per_year[tf])` — implicitly assuming a trade occurs on every bar. That assumption is
badly wrong whenever trades are meaningfully less frequent than bars, which is the normal case:
at 1h (this project's dominant scale), `bars_per_year=1638` (`sqrt≈40.5`); at 1m,
`bars_per_year=98,280` (`sqrt≈313.5`) — a ~7.7x larger, categorically wrong multiplier applied to
strategies that might only trade a dozen times across multiple years of 1-minute bars, producing
exactly the -279.58/-590.15 magnitudes observed.

**Fixed to annualize by the trade sequence's own OBSERVED frequency**
(`sqrt(n_trades / years_covered)`, `years_covered` derived from the trades' own entry/exit
timestamps), not a per-timeframe lookup table. Verified with a new synthetic test
(`debug/_verify_compute_metrics_sharpe_annualization_fix.py`, 5/5 — including a check that the
fixed Sharpe is now IDENTICAL regardless of which `tf` label is passed, since it's derived from
real timestamps rather than a hardcoded table, and a check that a single trade correctly returns
NaN rather than a fabricated value from an undefined time span).

**A full audit was run before assuming the blast radius** (first alarmed Ross with an overstated
claim that headline paper Sharpes were broadly affected — corrected immediately once the audit
completed; see the session transcript for the full back-and-forth). Direct trace of every
function that produces a Sharpe number ANYWHERE in this project's cited results:

| Function | Convention | Affected? |
|---|---|---|
| `backtest.py:aggregate_portfolio()` (the actual project-wide headline, per CLAUDE.md's own "capital-constrained/portfolio results are the headline" rule) | daily-resampled P&L, `sqrt(252)` | **No** |
| `portfolio_math.py:sharpe_from_trades`/`sharpe_from_daily_pnl` | same daily-resampled convention | **No** |
| `sensitivity.py:_portfolio_sharpe()` (§7.8's entry/exit z-score grid, 9.178-10.59) | same daily-resampled convention | **No** |
| `portfolio_sim.py:portfolio_sharpe_from_replay()` (tonight's own Finding #48 capital-constrained numbers) | same daily-resampled convention, explicitly matched to `aggregate_portfolio()` per its own docstring (BUG-D62 precedent) | **No** |
| `fresh_holdout_compare.py:_pooled_sharpe()` | same daily-resampled convention | **No** |
| `backtest.py:compute_metrics()` (per-PAIR diagnostic rows only) | the buggy bars-per-year formula | **Yes** |

Every number `PAPER.md`/`PAPER_MAGNITUDE.md`/`README.md` cites as a headline claim (5.24, 5.80,
9.178, 10.59, 8.542, the `sharpe_portfolio`/OOS-Sharpe family throughout) comes from the
UNAFFECTED functions. A targeted grep across `README.md`, `docs/FINDINGS.md`, `docs/HANDOFF.md`,
`PAPER.md`, and `PAPER_MAGNITUDE.md` for any pair-name-plus-Sharpe citation found only two prose
spots referencing per-pair Sharpe, neither citing a now-wrong specific number: `PAPER.md` §6.6
("individual pair Sharpes... argue for real per-pair skill" — softened to cite win rate/total P&L
instead, since those are unaffected) and §7.8 ("highest single-pair-level Sharpe... 10.068" — the
NUMBER is correct, already from the unaffected `_portfolio_sharpe()`; only the misleading
"single-pair-level" label needed fixing, corrected to "pooled, portfolio-level"). Confirmed via
grep that `compute_metrics()`'s per-pair output is read only by `reproduce.py` for reporting —
never consumed by any pair-selection or capital-allocation logic, so no methodology decision was
ever silently corrupted by this bug, only diagnostic reporting.

**Regenerated all 159 `output/backtest/*summary*.parquet` files** from their already-cached
matching trades files via the fixed formula (`research/regenerate_summary_layer1_sharpe_fix.py`)
— 157/159 succeeded (2 skipped cleanly: `wfa_summary_{expanding,rolling}.parquet`, which pair
with `wfa.py`'s own differently-schemaed trades files, out of scope for this pass). Real,
substantial shifts confirmed (max observed `|old_sharpe - new_sharpe|` across all files:
12,359.54, driven by the same short-history/high-annualization-multiplier mechanism as the
1m/2m decoupling case). `baseline_summary_layer1.parquet`'s 31 production pairs shift by a
median of ~90% in magnitude (e.g. LNT/WELL@1h/ols: 38.77 → ~3.67) — a large, real change to
these DIAGNOSTIC per-pair numbers specifically, with zero change to any cited headline claim.

Files: `backtest.py` (`compute_metrics` fix), `debug/_verify_compute_metrics_sharpe_
annualization_fix.py` (new, 5/5), `research/regenerate_summary_layer1_sharpe_fix.py` (new),
`PAPER.md` (§6.6/§7.8 wording corrected), all 157 regenerated `output/backtest/*summary*.parquet`
files.

**Follow-up, re-running `decoupling_backtest.py` itself (the file that originally surfaced the
bug — it doesn't persist raw trades separately, so needed a full re-run rather than a
recompute-from-cache):** the 1m/2m pairs' Sharpe magnitudes are STILL large under the fixed
formula (SPY/VOO@1m: -63.90; SPY/VOO@2m: -95.59) — but this is now a genuinely different,
non-bug issue: `n_post_settling_bars` for these pairs is 3,195-4,560 BARS at 1m/2m resolution,
i.e. only ~2.2-3.2 CALENDAR DAYS of post-break history. Annualizing any Sharpe computed from a
multi-day sample is inherently statistically unstable — extrapolating a few days' realized
volatility to "if this repeated for a full year" mathematically produces extreme magnitudes
regardless of which correct annualization formula is used; this is a small-sample-window
limitation, not a coding bug. Only `ETN/PH` (1D timeframe, `n_post_settling_bars=3243` calendar
DAYS ≈ 8.9 years) has an evaluation window long enough for its annualized Sharpe (-0.1047) to be
read as remotely meaningful. **Phase 3's meta-analysis (next) is scoped accordingly**: Sharpe-
based synthesis is not attempted across all 4 requalified pairs; the requalification p-values
(which don't depend on backtest-window length at all) are the clean, defensible basis for a
formal small-n meta-analysis instead.

## 52. Phase 3 of the Discovery-Event Research Program: Formal Meta-Analysis of the Decoupling
Chain — a Clean, Honest Null on Aggregate Trading Edge [2026-09-04]

`research/decoupling_meta_analysis.py` (verified first, `debug/_verify_decoupling_meta_
analysis.py`, 10/10) combines the `decoupling_analysis.py` → `decoupling_requalification.py` →
`decoupling_backtest.py` chain's own results — a genuinely related hypothesis family (every
stage tests the same underlying question: does a pair's post-break cointegration re-formation
represent something real and tradeable?), not an arbitrary grab-bag, per Ross's own "auditing
which nulls test a genuinely related hypothesis before combining them" scoping. Each individual
stage is underpowered alone (5/142 pairs requalify; only 4 reach a real backtest; 1/4 profitable)
— the meta-analysis asks whether combining them surfaces anything the individual results miss.

**Two formal combinations, both run**: (1) Fisher's combined p-value on the 4 requalification EG
p-values: χ²=220.50, combined p=3.02e-43 — extremely significant, but not very informative on its
own, since all 4 already individually clear 0.05 and 2 of the 4 (both involving SPY/VOO) have
already-extreme individual p-values (5.5e-16, 1.4e-29) that dominate the combined statistic.
Disclosed caveat: 3 of the 4 pairs share SPY/VOO, so Fisher's independence assumption is not
fully met — the combined p-value is a soft upper bound on the true joint evidence, not a strict
formal guarantee. (2) The more informative test: a one-sample t-test AND sign test on the 4
backtested pairs' TOTAL P&L (not Sharpe — see Finding #51's follow-up on why annualized Sharpe is
unstable for 3 of these 4 pairs' short evaluation windows). **Real result: mean P&L = -$9.54,
t=-0.153, p=0.888; 1/4 pairs positive, sign-test p=0.625** — a clean, honest null. Even under a
proper small-n meta-analytic combination (not just eyeballing "1/4 positive"), there is no
detectable aggregate trading edge across the requalified-and-backtested set.

**Read plainly**: this reinforces, rather than overturns, Ross's original 2026-07-01 decision to
keep the entire decoupling line of work as research-only. It upgrades that decision from an
informal "1 of 5 positive, not enough" read to a formally-tested null with an honestly-reported
(and honestly tiny) sample size — n=4 is far too small for this null to rule out a real effect
existing, but the point estimate itself sits near zero, not just noisy around something larger.
Phase 3, as scoped, is now complete.

Files: `research/decoupling_meta_analysis.py` (new), `debug/_verify_decoupling_meta_analysis.py`
(new, 10/10), `output/research/decoupling_meta_analysis.parquet`, `output/research/decoupling_
backtest.parquet` (re-run with the fixed `compute_metrics`, per Finding #51's follow-up).

## 53. Phase 4 of the Discovery-Event Research Program: a Diversification-Basket Signal (Noisy
Null) and a Hedge-Blend Test (Clean Negative — Pair-Only Beats Every Blend) [2026-09-04]

The final piece of the 4-phase combined research program Ross scoped at the start of this
multi-hour thread. Two scripts (`research/diversification_basket_test.py`,
`research/hedge_blend_test.py`), verified first (`debug/_verify_diversification_basket_test.py`
10/10, `debug/_verify_hedge_blend_test.py` 7/7). **A real infrastructure lesson surfaced before
either produced a result**: both scripts silently OOM-killed
twice on the local Windows machine (looked like hangs at first, confirmed via
`Get-CimInstance Win32_OperatingSystem` showing ~4GB free of 16GB) before being moved to CachyOS
per the project's own standing "never use the Surface for RAM-heavy work" rule — a
`universe_loader.load_full_universe()` call, even with `columns=["close"]` filtering, needs
CachyOS just as much as the WRDS-daily PIT work earlier in this same session did. A missing input
(`correlation_transitions.parquet`, a Phase-1 local-only output never previously synced) had to
be copied over before either script could run there.

**Part A — `diversification_basket_test.py`: does a basket of currently-uncorrelated assets show
a real diversification benefit vs. correlated or random baskets?** Real result, honestly noisy,
no clear signal:

| basket_size | coint | not_coint | random_control |
|---|---|---|---|
| 10 | 1.5813 | 1.4844 | 1.3226 |
| 20 | 2.2194 | 2.0537 | 1.3291 |
| 30 | 1.2854 | 2.1975 | 2.0644 |

At n=10/20, `coint` > `not_coint` > `random`; at n=30, the order flips (`not_coint` > `random` >
`coint`). No consistent ordering across basket sizes — "currently decoupled" status does not show
a reliable extra diversification benefit beyond a random basket. Disclosed limitation, not
silently absorbed: this is a single-draw-per-arm design (one random basket per size/arm, no
repeated sampling for a confidence interval) — a real next step if this line is pursued further,
not yet a robust statistical test.

**Part B — `hedge_blend_test.py`: does blending the real production pair-trading strategy
(`baseline_trades_layer1.parquet`, 1,340 trades, 2023-08-14 to 2026-07-02) with a currently-
uncorrelated 20-symbol basket improve Sharpe, swept across blend weight w ∈
{1.0, 0.9, 0.8, 0.7, 0.6, 0.5}?** **Real result: a clean negative.** Sharpe declines
monotonically as more weight shifts into the hedge basket — w=1.0 (pure pair strategy, the
with/without baseline): Sharpe **6.0021**; w=0.9: 5.9840; w=0.8: 5.5659; w=0.7: 4.7792; w=0.6:
3.8410; w=0.5: 2.9557. Volatility does bottom out at w=0.9 (0.004265, lower than w=1.0's
0.004642) before rising again at heavier hedge weights — a small, real volatility-reduction
effect exists — but mean daily return falls faster than volatility falls as hedge weight
increases, so Sharpe never improves at any tested blend. **Read plainly**: this project's real
production pair strategy already has a very strong risk-adjusted edge (Sharpe ~6, portfolio-
level, the correct convention per Finding #51's audit) — diluting it with a lower-expected-return
uncorrelated basket, even a genuinely uncorrelated one, is a net drag once the basket's own near-
zero alpha is accounted for. Diversification helps volatility in isolation; it does not help
Sharpe here because the asset being added has nothing like the pair strategy's own edge.

**Phase 4, and the full 4-phase discovery-event research program, is now complete.** Both parts
report honest results (a noisy null and a clean negative) rather than results reshaped to look
more positive — consistent with this entire multi-hour thread's discipline (Findings #45-53:
real signals reported when found — coint_strength_z/decay_rate, Finding #49 — and real nulls/
negatives reported plainly when that's what the data showed — Findings #50, #52, #53).

Files: `research/diversification_basket_test.py` (new), `research/hedge_blend_test.py` (new),
`debug/_verify_diversification_basket_test.py` (new, 10/10), `debug/_verify_hedge_blend_test.py`
(new, 7/7), `output/research/diversification_basket_test.parquet`, `output/research/hedge_
blend_test.parquet`, `output/research/correlation_transitions.parquet` (synced to CachyOS).

## 54. Phase 1 of the New Backlog Items: Options Greeks Unit, Portfolio Risk Metrics (Sortino/
Rolling Sharpe/Calmar/M2), and a Per-Asset Volatility Profile [2026-09-07]

Ross approved a build-order for a new backlog of previously-unscoped items (queued 2026-09-04),
picking a leverage-first sequence: cheap/foundational pieces before the two architecturally
significant ones (beta-weighting, confidence-score allocation). Phase 1 (all three, low-risk, no
open design questions) built and verified today.

**Options Greeks unit** (`options.py`): added `black_scholes_delta/gamma/vega/theta`, a
`black_scholes_greeks()` convenience wrapper, and a vectorized `black_scholes_greeks_vectorized()`
— directly closes the "options calc unit... consider things in terms of delta" backlog item.
Reuses `options.py`'s existing, already-verified `black_scholes_call/put` conventions (zero
risk-free rate, same guard behavior at T≤0). Verified against finite-difference derivatives of
the existing pricing functions (`debug/_verify_options_greeks_unit.py`, 15/15) — not just
algebra copied from memory, an independent numerical cross-check. **A real duplicate found and
consolidated along the way**: `research/options_greeks_features.py` (built 2026-08-02, a
gamma-mismatch/correlation study) had its own byte-for-byte copy of the same Greeks math;
refactored to call the new shared `black_scholes_greeks_vectorized()` instead, removing the
duplicate and its now-unused `norm` import — a single source of truth going forward, matching
this project's own established anti-duplication discipline. Re-verified the existing
`debug/_verify_options_greeks_features.py` suite passes unchanged after the refactor.

**Portfolio risk metrics** (`portfolio_math.py`, this project's own canonical daily-P&L/Sharpe
module — extended rather than reimplemented, per its explicit "single source of truth" mandate):
added `downside_deviation`/`sortino_from_daily_pnl`/`sortino_from_trades` (semi-deviation
Sortino, the textbook formula — not `std()` of just the negative subset, which would silently
shrink N), `rolling_sharpe` (a trailing-window Sharpe time series, `min_periods=window` by
default so no noisy partial-window values sneak in), `calmar_from_daily_pnl` (textbook
annualized-return/max-drawdown, requiring `starting_capital` explicitly — never silently assumes
a capital base), and `m2_ratio` (Modigliani-Modigliani, rescaling the strategy's Sharpe to the
benchmark's own volatility so it's directly comparable in return terms, zero risk-free rate
matching this project's convention throughout). Verified
(`debug/_verify_portfolio_math_risk_metrics.py`, 9/9), including a direct cross-check that the
new `calmar_from_daily_pnl` matches `portfolio_sim.py`'s existing, independently-implemented
`calmar_from_replay()` exactly (10.6597 vs. 10.6597) on the same trade data — confirms no drift
between the general-purpose and capital-constrained-replay-specific Calmar implementations.

**Per-asset volatility profile** (`research/asset_volatility_profile.py`, new): for each symbol
across the confirmed-pairs universe, computes current 21d/63d annualized realized vol (reusing
`options.py`'s `realized_vol_proxy`, the project's established IV-proxy convention), the average
daily (unannualized) absolute return — the literal "average daily volatility" Ross asked for —
and a vol PERCENTILE (where the current 21d vol sits within its own trailing 252-day history, so
"is this asset unusually volatile right now" rather than a bare, context-free number). Verified
(`debug/_verify_asset_volatility_profile.py`, 7/7). **Real result on the live confirmed-pairs
universe: only 11/55 symbols have a valid figure** — the rest are missing
`output/cache/{symbol}_1day.parquet`, a real, pre-existing coverage gap in the SAME cache
`options.py`'s own overlay work already depends on and already discloses, not a new bug this
script introduced. Not yet chased further; flagged for whoever next touches daily-cache coverage.

Diagnostic/profile-building output only — none of Phase 1 is yet wired into any position-sizing
or filtering logic; that's the separate, later, not-yet-scoped "confidence-score filter +
position allocation" item (Phase 4 of this new backlog).

Files: `options.py` (Greeks functions), `research/options_greeks_features.py` (deduped),
`portfolio_math.py` (Sortino/rolling-Sharpe/Calmar/M2), `research/asset_volatility_profile.py`
(new), `debug/_verify_options_greeks_unit.py` (new, 15/15), `debug/_verify_portfolio_math_
risk_metrics.py` (new, 9/9), `debug/_verify_asset_volatility_profile.py` (new, 7/7),
`output/research/asset_volatility_profile.parquet`.

## 55. Phase 2: Breeden-Litzenberger Risk-Neutral Density — Two Real Data-Quality Bugs Found and
Fixed Against a Live SPY Chain, Working Correctly After the Fix [2026-09-07]

`research/risk_neutral_density.py` (new): extracts the market-implied terminal-price
distribution from a live option chain, q(K) = e^{rT} * d²C/dK², per Ross's request. Sidesteps
`options.py`'s own documented historical-IV limitation entirely — Breeden-Litzenberger only
needs a snapshot, not a time series. Method: fit a smooth IV(K) curve (low-order polynomial, in
log-moneyness space — see below), rebuild smooth Black-Scholes call prices on a fine strike
grid, differentiate twice via central finite differences, clip negative density values (the
disclosed, standard fix for the numerical-differentiation noise problem Ross's own notes
flagged) and report how much probability mass got clipped rather than hiding it.

**Verified against the strongest available ground truth first**
(`debug/_verify_risk_neutral_density.py`, 13/13): Black-Scholes itself assumes a lognormal
terminal price, so pricing a synthetic call grid at a KNOWN constant vol and running it through
the full pipeline must recover that exact lognormal density — it does (shape match at 3 test
strikes, correct mode, correct sign and direction of skew response to an injected vol smile,
measured via a proper third-standardized-moment skewness statistic after an earlier, flawed
tail-mass-cutoff check was caught and replaced).

**Three real problems found and fixed while validating against a real live SPY chain, none of
them caught by the synthetic tests alone (by design — they're data-quality issues, not math
bugs):**

1. **Strike range**: SPY's full exchange-listed range ran $150-$1000 against a $770 spot —
   deep ITM/OTM strikes with unreliable quotes broke the smoothing fit entirely (an implausible
   skewness of 61, density collapsed to near-zero everywhere but a razor-thin band). Fixed:
   restrict to a disclosed, explicit liquid moneyness band (`moneyness_band=(0.7, 1.3)` default)
   before fitting.
2. **yfinance's own `impliedVolatility` column is unreliable**: checked directly on a real
   chain (both a near-dated, normally-liquid expiry and a far-dated one) — every deep-ITM
   strike read exactly `1e-05` (a degenerate placeholder, not a solved value), and the OTM side
   showed an implausible exact-doubling staircase, not a real smile. This directly contradicted
   `options.py`'s own docstring claim that "yfinance's live option_chain() DOES include a real
   impliedVolatility column" — that claim is now corrected. Fixed: derive IV independently via
   numerical Black-Scholes inversion (`implied_vol_from_price`, `scipy.optimize.brentq`) against
   a real transaction price — exactly the "pull strikes and mid price yourself" approach in
   Ross's own original notes, not yfinance's precomputed field.
3. **Bid/ask were both zero across the entire chain** in this session's live snapshot (the
   market was very likely closed at fetch time). Fixed: fall back to `lastPrice` when bid/ask
   aren't live, with the fallback count explicitly reported (`used_stale_last_price`) rather
   than silently blended in as if it were a live quote.

**A fourth attempted fix that did NOT help, disclosed rather than hidden**: switching the
smoothing fit from raw-strike to log-moneyness space (`ln(K/S)`, standard practice for wide
dollar-strike ranges) was tried first and made no measurable difference on the real data — the
actual problem was the unreliable IV input (#2 above), not the fit's coordinate domain. Kept the
log-moneyness domain anyway (it's still better practice and didn't hurt), but the real fix was
#2/#3.

**Real result after all three fixes, on SPY's 2026-09-18 expiry (11 days out)**: 197/260
in-band strikes had a computable implied vol (255/260 priced off a stale `lastPrice`, confirming
the market was closed), only 9.4% of grid points needed negative-density clipping and the
clipped mass was ~0 (a clean, trustworthy extraction). Extracted distribution: mean 771.2 (vs.
spot 770.19), std 30.22 (plausible for an 11-day horizon — a rough 20%-annualized-vol estimate
gives ~26.8, the same ballpark), skew 1.301 (meaningfully right-skewed in price-level terms, the
expected lognormal-family baseline shape), with a smoothed IV curve showing a proper smile
(declining from OTM-put side toward a ~13-16% ATM low, rising again on the OTM-call side) rather
than the earlier garbage.

**Not yet built**: the "backtest-overfitting-detector" application Ross's own notes floated
(comparing a strategy's assumed/realized P&L distribution against the market's live RND for the
same underlying/horizon) — flagged as the natural next step once this core extraction has been
run and sanity-checked a few more times across different symbols/expiries/market-open conditions.

Files: `research/risk_neutral_density.py` (new), `debug/_verify_risk_neutral_density.py` (new,
13/13), `options.py` (docstring correction re: impliedVolatility reliability),
`output/research/risk_neutral_density_SPY_2026-09-18.parquet`.

## 56. Phase 3: Beta-Weighting Against SPY — Hedging Residual Market Exposure Has a Real Cost,
Consistent With Every Other Hedging Result This Project Has Found [2026-09-07]

`research/beta_weighted_portfolio.py` (new): pairs trading is theoretically market-neutral (long
one leg, short the other), but the two legs' own market betas are never actually forced equal —
cointegration confirmation says nothing about beta matching. This measures the resulting net
dollar market-beta exposure directly against SPY (WRDS total-return-adjusted, this project's
priority source), per Ross's explicit scoping ("use SPY and compare both hedge and report
only"). Per-leg beta: causal rolling regression beta (`cov(asset, SPY)/var(SPY)`, 63-day window,
held constant for a trade's holding period), verified against a known-injected-beta synthetic
case (`debug/_verify_beta_weighted_portfolio.py`, ultimately 16/16). **A real bug caught by the
verify suite before running on real data**: `build_daily_net_exposure`'s `pd.date_range` call
didn't normalize its start/end to midnight, so for sub-daily-timeframe trades (real entry times
like `"2023-10-02 14:00:00"`) every generated calendar day silently inherited that same intraday
offset, causing a `KeyError` on every real lookup — fixed by normalizing both endpoints, with a
new check reproducing the exact scenario.

**Real result, both arms**: REPORT-ONLY — net beta exposure relative to an assumed $100,000
capital base: mean -0.4704 (-47%), std 1.4341, max\_abs 14.67 (a huge apparent leverage figure,
explained below, not literally 1467% margin). HEDGE — daily-offsetting SPY overlay recomputed
through this project's own canonical `portfolio_math.py` metrics:

| | Sharpe | Sortino | Calmar | Total P&L |
|---|---|---|---|---|
| Unhedged | 6.0581 | 35.1947 | 29.6516 | $184,417.64 |
| Hedged | 2.6681 | 4.1218 | 1.6814 | $155,100.90 |

**Hedging the residual beta exposure makes every risk-adjusted metric worse, not better** —
consistent with, not contradicting, `options.py`'s own earlier protective-put/call finding (a
real, disclosed hedging cost, not a free lunch) and the project's broader pattern this session of
honest negative/null results (Findings #50, #52, #53) sitting alongside real positive ones.

**A real, disclosed caveat on the exposure-scale numbers specifically** (not the Sharpe
comparison, which is a real dollar-P&L computation independent of any assumed capital base):
`baseline_trades_layer1.parquet` is `backtest.py`'s RAW, capital-UNCONSTRAINED per-pair trade
output (fixed `N_SHARES_PER_TRADE` sizing, no shared capital pool across overlapping positions —
the exact BUG-D60 property `portfolio_sim.py`'s own docstring already documents). The
$100,000 "starting capital" used to express exposure as a percentage is therefore an ILLUSTRATIVE
scaling choice, not the trades' real, enforced capital base — the max\_abs=14.67 figure should be
read as "this many multiples of $100k in dollar notional mismatch at the peak," not literally
1,467% real account leverage. A capital-constrained version (running this same beta-exposure
measurement against `portfolio_sim.py`-replayed, capital-constrained trades instead of the raw
backtest output) would give a materially more realistic exposure-scale reading and is flagged as
the natural refinement if this line of work continues.

Files: `research/beta_weighted_portfolio.py` (new), `debug/_verify_beta_weighted_portfolio.py`
(new, 16/16), `output/research/beta_weighted_portfolio.parquet`.

## 57. Phase 4: Confidence-Score Filter + Position Allocation — the Score, as Designed, Does the
OPPOSITE of What It Should; a Real, Honest Negative Result, Not Spun as a Success [2026-09-07]

`research/confidence_score_allocation.py` (new): the last, most architecturally significant item
of the new backlog, deliberately built last so it would have Phase 1-3's real signals to consume.
Per Ross's own framing ("confidence score as filter, then position allocation. max points in
each category = 100%"): combines 4 categories, each contributing up to 25 points (equal
weighting, a disclosed default) via PERCENTILE RANK within the real trade set (data-derived, not
an arbitrary fixed scale) — statistical confirmation strength (`hurst_at_entry`, lower = better),
reversion speed (`half_life_at_entry`, shorter = better), volatility-regime normality (Phase 1's
`vol_percentile`, closer to 0.5 = better), and market-neutrality quality (Phase 3's per-trade
beta mismatch, smaller = better). Verified first (`debug/_verify_confidence_score_allocation.py`,
ultimately 17/17 after several test-construction mistakes were caught and fixed — using too few
synthetic trades for percentile ranking to be meaningful, and a misunderstanding of pandas
`rank(pct=True)`'s exact boundary behavior).

**Validated, not just asserted, via a real filter-threshold sweep on the 616-trade production
set — and the validation is a clear, honest NEGATIVE result**: filtering to HIGHER confidence
scores makes every metric progressively WORSE, not better —

| score ≥ | n_trades | Sharpe | Sortino | Calmar | Total P&L |
|---|---|---|---|---|---|
| 0 (no filter) | 616 | 6.0581 | 35.1947 | 29.6516 | $184,417.64 |
| 25 | 553 | 5.8654 | 32.9781 | 25.3195 | $161,220.71 |
| 50 | 318 | 4.5566 | 17.8228 | 11.7899 | $81,118.39 |
| 75 | 67 | 1.5175 | 3.0263 | 1.5918 | $8,827.77 |

Overall `confidence_score`-vs-`pnl_net` correlation: **-0.1295** — the opposite sign of what a
useful filter needs. Diagnosed per-category rather than left as an unexplained failure: the main
driver is `score_reversion_speed` (-0.1954 correlation) — faster-reverting trades (the higher-
scoring ones under this design) do NOT predict better P&L; if anything, slower-reverting trades
that run longer appear to capture more profit under this project's fixed-shares-per-trade sizing
convention (a trade held longer has more room to accumulate P&L before its fixed exit rule
fires). `score_confirmation` (-0.0317) and `score_beta_neutrality` (-0.0218) are both weak/
negligible either direction. `score_vol_regime`'s correlation is **undefined (NaN)** — a direct,
compounding consequence of Finding #54's already-disclosed 11/55 volatility-profile coverage gap
propagating forward into this score: most trades simply never get a vol-regime component at all.

**Read plainly, not spun**: this is not "confidence scoring doesn't work" — it's "THIS
particular set of 4 categories, equally weighted, does not predict trade quality in this real
dataset, and one category (reversion speed) is actively anti-predictive under the current
design." The individual building blocks (Greeks, risk metrics, volatility profile, RND, beta
exposure) built in Phases 1-3 are all real, independently-verified, working tools — Phase 4's
finding is that NAIVELY combining them with equal weights and an unexamined "lower is always
better" direction assumption per category does not produce a useful filter here. Real next steps,
not yet done: drop or invert the reversion-speed category (or investigate WHY slower reversion
predicts more P&L before deciding), fix the underlying volatility-profile cache-coverage gap so
that category can contribute at all, and re-test with a properly cross-validated (not same-
sample) threshold choice before any of this is used for real position sizing.

This completes the full 4-phase new-backlog build Ross scoped at the start of this session
(Findings #54-57) — three phases produced real, working, positively-validated tools; the fourth
produced an honest, diagnosed negative result rather than a system declared "done" by assertion.

Files: `research/confidence_score_allocation.py` (new), `debug/_verify_confidence_score_
allocation.py` (new, 17/17), `output/research/confidence_score_allocation_trades.parquet`,
`output/research/confidence_score_allocation_sweep.parquet`.

## 58. `options.py:load_price_series()` Never Checked WRDS at All (Real, Significant Coverage
Bug); Per Ross's Instruction, yfinance Fallback Removed Entirely (WRDS/IBKR Only); Phase 3-4
Re-Run With Full Coverage — the Phase 4 Negative Finding Holds, Now Cleanly Attributable
[2026-09-08]

While starting Phase 4's flagged redesign work (fix the volatility-cache gap first), traced
Finding #54's "only 11/55 symbols have valid volatility data" result to its actual root cause:
`options.py:load_price_series()` only ever checked the yfinance-only `{symbol}_1day.parquet`
cache — it never looked at `output/cache/wrds/{symbol}_1D.parquet` at all, silently violating
this project's own "WRDS takes complete priority" rule (CLAUDE.md) for every caller of this
function: `options.py`'s own protective-overlay work, `research/options_greeks_features.py`, and
`research/asset_volatility_profile.py`. Confirmed directly: 44 of the 55 "missing" symbols had
real WRDS-cached data the function simply never looked at.

**Per Ross's explicit instruction mid-fix ("don't use yfinance, use wrds or ibkr")**: rather than
add WRDS as a higher-priority fallback ahead of yfinance (the initial fix), the yfinance fallback
was removed entirely. `load_price_series()` now checks WRDS (`close_total_return`, CRSP total-
return-adjusted) first, then IBKR's deep-history supplement (`ibkr_supplement_reader.py`, native
1D bars, a small ~92-symbol confirmed-pair set per `universe_loader.py`'s own documented scope),
and returns `None` if neither has the symbol — a real, disclosed coverage tradeoff (~1,731
symbols in this project's cache only ever had yfinance daily data, and now return `None` here
rather than falling back to it), not a bug. Verified
(`debug/_verify_options_load_price_series_wrds_fallback.py`, 6/6, including a check that a
yfinance-cached symbol with no WRDS/IBKR data correctly now returns `None` rather than silently
reaching for yfinance).

**Real result on the confirmed-pairs universe (Finding #54's original test): 37/55 symbols now
get a valid volatility figure (up from 11/55), using WRDS/IBKR only.**

**A second, independent real bug found while re-running Phase 3/4 with the fix**: Phase 4's
per-trade volatility-regime category was still failing for nearly every trade even after the
`load_price_series` fix — traced to a methodology mismatch, not a data gap: the pre-computed
`asset_volatility_profile.parquet` (Finding #54) was built over `confirmed_pairs_list()`'s
CURRENT confirmed-pair universe (55 symbols), but `baseline_trades_layer1.parquet`'s actual
traded symbols turned out to be almost entirely DISJOINT from that set — only 1 of 24 traded
symbols appeared in the file at all, strongly suggesting `baseline_trades_layer1.parquet` is a
legacy trades file from an earlier, different confirmed-pair set. Fixed by computing the
volatility profile ON DEMAND in `confidence_score_allocation.py`, for exactly the symbols the
run actually needs, reusing `asset_volatility_profile.py`'s own `compute_volatility_profile()`
function rather than depending on a static file that may not cover the trades in question.

**Phase 3 and 4 re-run with the fixes. Phase 3's qualitative conclusion holds, with updated real
numbers** (data source changed for the beta estimates, from a yfinance/WRDS mix to WRDS/IBKR
only): unhedged Sharpe=6.0581 (unchanged, sourced from `pnl_net` directly), hedged Sharpe now
0.5019 (was 2.6681), hedged Calmar 0.9869 (was 1.6814) — hedging still makes risk-adjusted
performance markedly worse, though hedged total P&L is now HIGHER in raw dollars ($245,190.86
vs. $155,100.90) — the ride is simply far more volatile hedged (Sortino collapses to 0.7360),
so the risk-ADJUSTED conclusion is unchanged even though the raw-dollar direction flipped.

**Phase 4's negative finding not only holds with full 4-category coverage, it becomes cleanly
attributable to a single category** rather than partly explained by a data gap:

| category | correlation with pnl_net (before fix, partial coverage) | correlation (after fix, full coverage) |
|---|---|---|
| confirmation | -0.0317 | -0.0317 (unchanged) |
| reversion_speed | -0.1954 | -0.1954 (unchanged) |
| vol_regime | NaN (0 valid) | **+0.0254 (616 valid, negligible)** |
| beta_neutrality | -0.0218 | -0.0086 (weaker, still negligible) |
| **overall confidence_score** | -0.1295 | **-0.1086** |

With full coverage, `score_vol_regime` is no longer undefined — it's simply negligible
(+0.0254), not a meaningful predictor either direction. The overall negative relationship is now
clearly and almost entirely attributable to `score_reversion_speed` alone, not partly an
artifact of the earlier coverage gap. This strengthens, rather than changes, Finding #57's real
next step: understand or drop the reversion-speed category specifically, since it's the one
genuinely anti-predictive signal here, not a symptom of missing data.

Files: `options.py` (`load_price_series` WRDS/IBKR fix), `research/confidence_score_
allocation.py` (on-demand volatility profile), `debug/_verify_options_load_price_series_
wrds_fallback.py` (new, 6/6), re-run outputs for `research/asset_volatility_profile.py`,
`research/beta_weighted_portfolio.py`, `research/confidence_score_allocation.py`.

## 59. The Backtest-Overfitting Detector — Built and Working: Real SPY Result Shows a Meaningful
Realized-vs-Implied Volatility Gap [2026-09-08]

`research/backtest_overfitting_detector.py` (new): the last unbuilt item flagged in Finding #55
— Ross's own notes on Breeden-Litzenberger floated "also a backtest overfitting detector."
Compares an asset's REALIZED historical return distribution against the market's CURRENT
risk-neutral density for the same asset (reusing `research/risk_neutral_density.py` directly,
not reimplemented). Both sides' moments (mean/std/skew) are computed via the identical weighted-
moment formula, factored into a single shared function (`weighted_moments`) so any difference
found is a real distributional difference, not an artifact of two slightly different moment
computations. The realized side uses NON-OVERLAPPING historical windows of the same length as
the option's time-to-expiry — a real, disclosed methodology choice: overlapping/rolling windows
share almost all their data with their neighbors and would understate the true sampling
uncertainty of the realized variance, making history look artificially more precise than it is.

Verified first (`debug/_verify_backtest_overfitting_detector.py`, 11/11): exact recovery of
mean/std for a known distribution, correct skew sign detection, an exact zero-volatility
sanity check (deterministic constant-growth series recovers its own known growth rate with std
exactly 0), and direct confirmation that windows are non-overlapping (`n_windows =
len(close)//window_bars`, not `len(close) - window_bars`).

**Real result on SPY's 2026-09-18 expiry (~9.7 days out, T=0.0265 years, 1,184 non-overlapping
historical windows)**: market-implied mean=0.0028, std=0.0377, skew=2.6678; realized
mean=0.0033, std=0.0256, skew=-0.5608. **Realized/implied volatility ratio: 0.679** — the market
is currently pricing in roughly 47% MORE near-term volatility than SPY's own recent history at
comparable horizons would suggest. Read plainly: this is directionally consistent with the
well-documented variance risk premium already disclosed in `options.py`'s own docstring
(implied vol systematically exceeds subsequently-realized vol) rather than a surprising anomaly
— exactly the kind of check this tool exists to surface, whether the gap turns out mundane (the
usual variance risk premium) or a genuine regime signal worth investigating further before
trusting a backtest calibrated to the calmer historical period. The skew comparison is also
notable: implied skew is strongly positive (2.67, the expected lognormal-family baseline shape
in price-level terms per Finding #55) while realized skew is negative (-0.56) — a real shape
divergence between what the market currently expects and what recent history actually looked
like, not yet interpreted further in this first pass.

This completes every item flagged across Findings #54-58 as "not yet built" or "natural next
step" from the original 2026-09-04 backlog plus Ross's Breeden-Litzenberger idea.

Files: `research/backtest_overfitting_detector.py` (new), `debug/_verify_backtest_
overfitting_detector.py` (new, 11/11), `output/research/backtest_overfitting_detector_
SPY_2026-09-18.parquet`.

## 60. `PAPER_MAGNITUDE.md` — the Two Real Results Sitting Unintegrated Are Now Folded In;
Every Substantive Section Is Now `[DRAFTED]` [2026-09-08]

Ross asked whether the new backlog data (Findings #54-59) impacts the paper. The direct answer
was mostly no (options Greeks, RND, confidence-score, beta-hedging are tangential to the
discovery-event thesis, better routed to the companion paper or left as standalone notes) — but
checking prompted a more important discovery: `PAPER_MAGNITUDE.md`'s own §10 (Future Work) named
its two biggest, most explicitly flagged open items — *"re-run §4's PIT-lookahead test at the
corrected ~44,700-symbol scale, the most important item on this whole list"* and *"directly test
whether the crisis-regime pattern survives controlling for market-wide factor co-movement"* —
and both already had real, computed answers from earlier this session (Findings #46-48 and
Finding #46 respectively) that had never been folded into the paper text itself.

**§5's confound integration was already done** (checked, not assumed — grep confirmed the
residual-correlation result is present in §5/§8's confound discussion from earlier session work).

**§4's corrected-scale re-run was NOT integrated — the paper's own single most important open
item, now closed.** Added a new block to §4 reporting `pit_wfa_wrds_daily.py`'s real 4-fold
result at the full ~43,883-symbol WRDS-primary, daily-bar universe (the same universe §5 draws
from; each PIT fold's own candidate-pair count is smaller and cutoff-specific, not a shared
figure with §5's full-history 638,095-pair count — a real distinction fixed in the paper text
after an initial draft conflated the two) (expanding/fold1:
11/21 trades, Sharpe=-0.4779; expanding/fold2: 25/50, Sharpe=+0.1918; rolling/fold1: identical
to expanding/fold1 by construction; rolling/fold2: 309/1,533 trades, Sharpe=+0.2175, the single
largest and most statistically substantive fold produced), including the two real bugs found and
fixed along the way (the `hurst_rs=None` `BacktestEngine` crash, the `portfolio_sim.py` WRDS-
daily wiring gap) as methodology footnotes, matching this section's own established pattern of
disclosing bugs-found-before-trusting-a-result as evidence of rigor. **Read honestly, not spun**:
the corrected-scale result does not resolve the causal-validity finding into a cleaner
confirmation or refutation — still 2 of 4 folds positive, 2 negative, the same qualitative
pattern the original smaller-scale table already showed. Updated in parallel, everywhere the old
"not yet re-run at corrected scale" language appeared: the Abstract, §1.4, and §8's limitations
bullet for §4 — each now states the real, mixed corrected-scale result instead of a placeholder,
with an honest new disclosure that the corrected-scale universe's own survivorship property
(present-day-cache-glob vs. a true PIT-safe reconstruction) was not separately re-verified in
this pass.

**§10 (Future Work) updated**: both resolved bullets marked **DONE** with their real results and
what remains genuinely open within each (a pooled-across-folds headline Sharpe for §4, requiring
equity-curve stitching not built; the survivorship confound for §5, not yet tested) rather than
deleted outright — preserves the honest record of what was asked and what was actually found.

**Every substantive section of the paper is now `[DRAFTED]`** — §1 (Introduction) was fully
written prose already, just carrying a stale `[OUTLINED]` tag from an earlier drafting stage;
corrected. Only §10 (Future Work, a bullet list by nature, not narrative prose) remains
`[OUTLINED]`, appropriately.

Files: `PAPER_MAGNITUDE.md` (Abstract, §1.4, §4, §8, §10 updated; §1's status tag corrected).

## 61. Sequential Bootstrap / Average-Uniqueness Weighting — First of PAPER.md §10's Three
Future-Work Candidates Built, Real Result Modest and Noisy, Not a Clean Win

Ross (2026-09-08): after an explicit design discussion (per CLAUDE.md's standing rule that a
new methodology gets discussed before being built), approved building this as the first of
§10's three candidates, resolving the one real open design question flagged during that
discussion: overlap is computed **per pair** (each `(symbol_a, symbol_b, tf_label)`'s own
entry-event sequence is the underlying "series" AFML Ch. 4's average-uniqueness concept applies
to), not pooled across different pairs — two different pairs trading at the same wall-clock time
is a portfolio-concurrency question, not a labeling-uniqueness one.

`research/sequential_bootstrap_ml_comparison.py` (new): built as a comparison arm alongside
`ml.py`'s existing training scheme, per CLAUDE.md's rule that a new methodology never goes
straight into production. Reuses `ml.py`'s exact chronological train/val/test split and XGBoost
hyperparameters unchanged; only the TRAIN split's sampling/weighting differs across three arms —
(A) baseline (`ml.py`'s existing "balanced" class-weight only), (B) average-uniqueness weighting
(no resampling), (C) full AFML Snippet 4.3 sequential bootstrap (iterative draw-with-replacement,
probability proportional to CURRENT average uniqueness, recomputed after every draw).
`debug/_verify_sequential_bootstrap_ml_comparison.py` (new, 11/11 checks): synthetic proof of the
overlap math, including a real bug caught and fixed live — the first implementation of
`_pair_average_uniqueness` equal-weighted each breakpoint instead of duration-weighting unequal-
length segments (an early boundary-sampling approach only checked OTHER labels' start events
within a span, missing the point where an overlapping label exits and concurrency drops
mid-span), which a partial-overlap synthetic case (uniqueness should land strictly between 0.5
and 1.0, not exactly 0.5) caught and the fix resolved.

Real data-pipeline gap found and fixed along the way: `ml.build()`'s standard full-history
screen and its PIT-safe episodic-adapter path both currently produce **zero** labeled examples
on this machine — traced to `output/results/*/spread_series_*.parquet` files that were computed
on CachyOS (this project's compute machine for RAM-heavy work) but never synced locally (only 9
of the real set existed here; `output/results/1day` had zero). Pulled the full `output/results`
tree from CachyOS via `tar`-over-`ssh` (no `rsync` available in this environment) — brought the
local count to 40 spread-series files, enough for the STANDARD (non-PIT-safe) screen to produce
237 labeled examples across 12 real confirmed pairs (the PIT-safe adapter path still mostly
misses — 181/182 of its pairs still have no matching spread series even after the sync, a
separate, larger gap not chased down further this session).

**Real result, on 237 real labeled examples (142 train / 47 val / 48 test, chronological split)**:
average uniqueness is 0.457 mean (min 0.093) — the effective unique training-example count is
~65, not the raw 142, confirming the exact overstated-sample-size bias this candidate was built
to address is real and substantial in this project's own data, not just a theoretical concern.
Single-seed result (seed 42): baseline test accuracy 56.25%, uniqueness-weighted 58.33%,
sequential bootstrap 66.67% — looked like a clean win. **Checked for seed sensitivity before
reporting, per this project's own discipline against overselling a single lucky draw**: across
10 random seeds, sequential bootstrap's test accuracy ranges 47.9%-72.9% (mean 59.4%, std 7.9pp)
against the baseline's fixed 56.25% — a modest average improvement (+3.1pp) but with 2/10 seeds
actually WORSE than baseline. Honest read: this is a real, disclosed positive signal at this
project's current tiny holdout size (n=48), not a decisive, stable win — consistent with the
sample size, not evidence the method doesn't work.

Files: `research/sequential_bootstrap_ml_comparison.py` (new), `debug/_verify_sequential_
bootstrap_ml_comparison.py` (new, 11/11), local `output/results/` tree refreshed from CachyOS.

## 62. Transfer Entropy Lead-Lag Detection — Second of the Three §10 Candidates Built, a Real
Off-by-One Bug Caught by the Synthetic Proof Before It Could Reach Real Data

`research/transfer_entropy_lead_lag.py` (new): Schreiber (2000) bivariate transfer entropy,
embedding dimension 1, quantile-binned (default 4 bins), following this project's existing
lead-lag-script conventions exactly (`aligned_pair_loader.load_aligned_pair`,
`data._gap_aware_returns` for GapFlag-aware returns per CLAUDE.md's non-negotiable gap-handling
rule, `pair_source.confirmed_pairs_list`). Significance via a permutation null built from
**circular shifts** of the Y series (not i.i.d. shuffling) — preserves Y's own autocorrelation
structure while destroying its specific temporal alignment with X, the more rigorous null for
time-series TE (i.i.d. shuffling would also destroy Y's autocorrelation, understating how much
apparent "coupling" could arise from shared smoothness/autocorrelation alone rather than real
information transfer).

**Real bug caught by `debug/_verify_transfer_entropy_lead_lag.py`'s synthetic proof before this
ever touched real data**: a known coupled system (`x[t] = 0.85*y[t-2] + noise`, true lag = 2)
should show TE peaking at lag 2 — the first implementation peaked at lag 1 instead, with the true
lag-2 signal appearing (mislabeled) one slot over. Root cause: `y_past = y[0:n-lag-1]` computes
`y[t-lag-1]`, not `y[t-lag]` — an off-by-one that silently tested `lag+1` under the `lag` label
for every call. Fixed to `y_past = y[1:n-lag]`; re-run of the synthetic proof confirmed the peak
lands on the true lag (5/5 checks). Exactly the kind of bug CLAUDE.md's "self-check against known
bug classes before running a new pipeline stage" rule exists to catch before it reaches a real
result — caught here by the debug proof precisely because one was built and run before trusting
the script on real pairs, not after.

Real data-pipeline gap, same shape as Finding #61's: of 27 confirmed 1D pairs, 26 returned
`no_data` from `load_aligned_pair` (base price data not locally cached, likely another CachyOS-
only-vs-local gap not chased down further this session, distinct from the spread-series gap
Finding #61 fixed). One real pair produced a result: AMP/RUSHA, best direction RUSHA→AMP at
lag=3, TE=0.0101 bits, permutation p=0.000 (significant) — a genuine, verified result, but from a
single pair, not yet a basis for any general claim about transfer entropy's value here. Broader
application blocked on the same category of local-cache gap as Finding #61, not on the method
itself, which the synthetic proof shows works correctly once given real, aligned price data.

Files: `research/transfer_entropy_lead_lag.py` (new), `debug/_verify_transfer_entropy_lead_lag.py`
(new, 5/5, including the off-by-one catch).

## 63. The "Local Price Cache Gap" Was Not a Sync Problem — `DataStore.load()` Never Checked
WRDS/IBKR At All, the Same Bug Class `options.py:load_price_series()` Already Had

Ross (2026-09-08): "we gotta fix the local price cache gap... make sure to keep both systems
synced." Investigation found the real root cause was NOT primarily a sync issue —
`research/aligned_pair_loader.py`'s `load_aligned_pair`/`load_aligned_symbols` (used by every
lead-lag/comparison script including the two new ones from Findings #61-62) call
`DataStore.load()`, which only ever reads `Config.DATA.CACHE_DIR` (`output/cache/`, the
yfinance-only cache) — no WRDS or IBKR fallback at all, directly contradicting this project's own
CLAUDE.md rule that WRDS/CRSP is primary for daily-and-coarser US equity/ETF, not yfinance.
Confirmed directly: Finding #62's one working pair (AMP/RUSHA) has yfinance cache; every failing
pair (BEAM/PERMNO10428, CBS/PERMNO20749, etc.) has WRDS cache but no yfinance cache — WRDS-only
symbols (PERMNO<n> fallback tickers, GVKEY<n> international listings) structurally cannot exist
in yfinance's cache regardless of sync state, since yfinance has no such tickers.

Fixed with the same WRDS-then-IBKR fallback pattern `options.py:load_price_series()` already
established this session, applied at the shared research-loader level (`aligned_pair_loader.py`,
explicitly NOT part of the production pipeline per its own docstring, the same safe scope
`options.py`'s earlier fix used — `DataStore.load()` itself, used throughout `data.py`/
`analysis.py`/`backtest.py`, was deliberately left untouched rather than risk changing its
semantics for callers this session didn't audit). New `_load_wrds_or_ibkr()` tried first
`close_total_return` (CRSP US-equity convention), a **second real bug caught while building the
fix**: Compustat Global international-listing files (`GVKEY<n>_<w>W` symbols) have no
`close_total_return` column at all, only plain `close` — the first version of this fallback
silently skipped every GVKEY-labeled symbol despite its WRDS cache file existing on disk. Fixed
to check `close_total_return` first, falling back to plain `close`; the identical bug was found
and fixed the same way in `options.py:load_price_series()` for consistency (it had the same
single-column check).

**Real effect, verified on Finding #62's own real-data scan**: `transfer_entropy_lead_lag.py --tf
1D` went from 1/27 confirmed pairs producing a result (26 `no_data`) to 16/27 producing a real
transfer-entropy result and the remaining 11 failing on `insufficient_bars` (genuine data
thinness for those specific short-history symbols, not a loading failure) — zero `no_data`
remaining. This was the real, structural fix; a caching-sync step alone (pulling more files from
CachyOS) would never have closed this gap, since the missing symbols never existed in yfinance's
cache on either machine.

**Live WRDS query, same session** (Ross offered to approve Duo): ran `data_wrds.py:fetch_ibes_
price_targets()` for real — Finding #60/PAPER.md §10's IBES script from earlier today. Connected
without an interactive Duo prompt (an existing trust window was still active). Real result:
1,133,381 rows, 10,316 distinct permnos, 1999-03-18 to 2025-12-18 — the schema-introspection
design worked correctly on the first real attempt, no wasted round-trip. Synced to CachyOS
immediately after.

**Both-systems sync, done this entry**: pushed every code file changed/created this session
(the two new research scripts + their verify suites, `data_wrds.py`, `aligned_pair_loader.py`,
`options.py`, `build_wrds_supplementary_data.py`, and the paper/doc files) to CachyOS via `scp`,
and the new `ibes_price_targets_camarf_universe.parquet` output the same way. Neither machine's
CAMARF checkout is currently on a common committed git state (both show real uncommitted diffs
against `origin`) — this sync was direct file copy, not git-based; worth a real commit-and-push
pass at a natural stopping point so both machines can sync via `git pull` instead of ad hoc `scp`.

Files: `research/aligned_pair_loader.py` (`_load_wrds_or_ibkr` fallback), `options.py`
(`close_total_return`/`close` column fallback), `data_wrds.py` (`fetch_ibes_price_targets` run
for real), `output/cache/wrds/ibes_price_targets_camarf_universe.parquet` (new, synced to both
machines).

## 64. Pooled-Across-Folds Headline Sharpe for the Corrected-Scale PIT Result — Built, Real,
Positive, and Genuinely Caveated (Not the Same as "Resolved")

The `pit_wfa_wrds_daily.py --variant both` re-run (launched earlier today after adding trade-level
persistence, Finding #58/HANDOFF's prior entry) completed on CachyOS: 176.2 min total. Every fold
reproduced its exact previously-reported summary metrics (fold1_roll: 11/21 trades, Sharpe=
−0.4779; fold2_roll: 309/1,533 trades, Sharpe=+0.2175) — confirms full determinism across the
re-run, and the new `pit_wfa_wrds_daily_taken_trades.parquet` output's per-fold row counts
(11/25/11/309) match `capital_sim`'s `n_trades_taken` column exactly.

`research/pit_wfa_pooled_equity_curve.py` (new) built the actual splice per the design agreed
with Ross before building (arithmetic-pooled across the fold boundary — no capital compounding;
the inter-fold calendar gap dropped via `portfolio_math.daily_pnl_from_trades`'s existing
per-trade-set-only zero-fill convention, not zero-filled; annualization keyed to the spliced
series' own actual daily-observation count). `debug/_verify_pit_wfa_pooled_equity_curve.py`
(new, 6/6) confirmed the gap-dropping behaves correctly on a synthetic 20-year-gap case AND
surfaced a real, worth-disclosing property before trusting the real result: **pooling weights by
calendar days present in each fold's own daily-zero-filled series, not by trade count** — a
synthetic 5-trade fold spread across 150 days produced 121 daily observations vs. a 2-trade fold's
2, a >10x observation-count difference from a trade count going the OPPOSITE direction.

**Real result**: pooled Sharpe is **+0.1845** (rolling variant, fold1_roll→fold2_roll) and
**+0.1285** (expanding variant, fold1_exp→fold2_exp) — both positive, both real, correctly
computed. **Read honestly, not spun as resolution**: fold1 (11 trades, Sharpe −0.4779) spans only
1946-1957 (4,018 daily observations); fold2_roll (309 trades, Sharpe +0.2175) spans 1996-2026
(10,988 daily observations, ~2.7x fold1's count) — fold2's much longer calendar span, not any
claim about it being more representative, is what dominates the pooled mean/std and produces the
positive sign. This answers PAPER_MAGNITUDE.md §10's exact open item (a genuine, non-fabricated
pooled figure) but should not be over-read: the underlying fold-to-fold sign disagreement (which
this project has reported as the honest headline story since the original 1h table) is still the
more accurate one-sentence summary than the single pooled number alone.

Files: `research/pit_wfa_pooled_equity_curve.py` (new), `debug/_verify_pit_wfa_pooled_equity_
curve.py` (new, 6/6), `output/backtest/pit_wfa_wrds_daily_taken_trades.parquet` (new, pulled from
CachyOS), `output/backtest/pit_wfa_wrds_daily_pooled_sharpe.parquet` (new), `PAPER_MAGNITUDE.md`
(§4 and §10 updated, plus a third stale "not built" reference to the same open item found and
fixed at the corrected-scale-vs-original comparison paragraph).

## 65. The Third §10 Item Built: Transfer Entropy Wired Into `ml.py` as a Real Feature, One Real
Negation Bug Caught Live, and a Striking (But Confounded) §4/§5 Interaction Result

Ross approved building all three remaining PAPER.md §10 items in one pass: transfer entropy as
an `ml.py` feature (the original candidate's own framing), the §4/§5 regime-vs-PIT-reconfirmation
interaction test, and the analyst price-target signal — resolved as a **pairs-relative overlay**
(not the literature's standalone single-name framing) specifically to keep it inside CAMARF's
existing co-movement architecture rather than introducing a new single-asset trade unit.

**Transfer entropy as an `ml.py` feature.** `research/transfer_entropy_lead_lag.py` gained
`summarize_pair_for_ml()`: reduces the full per-lag/per-direction scan to one
symbol_a/symbol_b-ORIENTED scalar per pair (`te_directional_diff` = TE(b→a) − TE(a→b) at the
single lowest-p-value lag; `te_significance` = 1 − that p-value) — fixed orientation, not
"whichever leg wins," confirmed by `debug/_verify_transfer_entropy_lead_lag.py`'s new checks
(10/10): a real test-authoring mistake was caught and fixed here too — the first "sign flips when
swapped" check actually swapped symbol_a/symbol_b LABELS while keeping the same real-world
coupling, which correctly does NOT flip the sign (the code was right, the test's own expectation
was wrong); fixed to hold labels fixed and reverse the real coupling instead, which does flip the
sign as required. `ml.py` gained the two new `EntryEvent` fields, added to `_FEATURE_COLS`, wired
via the same `pair_row.get(..., np.nan)` scalar-fallback convention `coint_fraction_rolling`
already uses (no per-bar PIT series needed — transfer entropy is a pair-level, not per-bar,
statistic). Confirmed live on real data: 237 examples now carry real, pair-specific
`te_directional_diff`/`te_significance` values (not all NaN), and a single-run holdout accuracy
ticked up to 62.50% from the prior 56.25% baseline (single run, not seed-averaged — a positive
sign, not a proven effect on its own, matching Finding #61's own caution against over-reading one
run).

**§4/§5 interaction test.** `research/pit_confirmation_vs_regime_interaction.py` joins §5's
638,095-pair crisis-regime diagnostic against §4's 320 unique PIT-confirmed pairs
(`pit_wfa_wrds_daily_pair_sets.parquet`), matching pairs in EITHER symbol_a/symbol_b order (the
diagnostic and the PIT screen order pairs differently — `debug/_verify_pit_confirmation_vs_
regime_interaction.py`, 8/8, specifically checks the reversed-order case matches). **Real overlap
checked and disclosed BEFORE running the test, not after**: only 18 of the 320 PIT-confirmed
pairs appear anywhere in §5's universe at all — a genuinely low-power test (≈0.05% base rate),
stated plainly in the script's own docstring, not glossed over. **Real result, striking but
requiring real caution**: pairs §5 flags as statistically-confirmed crisis-reappearance pairs are
PIT-confirmed at 1.72% (16/929) vs. 0.0003% (2/637,166) for everything else (z=98.7, p≈0); the
coarser `first_regime` label alone (crisis vs. calm discovery) shows the same direction, smaller
magnitude (0.034% vs. 0.001%, z=7.18, p≈0). **Read with real skepticism, not touted as a clean
joint finding**: both §5's "confirmed" flag and §4's PIT screen are independently selecting for
the SAME underlying property — genuinely strong, stable cointegration/correlation structure — so
this striking-looking result may just be two different statistical tests both detecting the same
real signal, not evidence of a novel regime-conditioning insight specifically. The absolute count
behind the strongest result (16 pairs) is also small enough that the z-statistic's apparent size
should not be over-read. Reported as a real, positive, but genuinely ambiguous result — the
honest next step (not built here) is testing whether the effect survives controlling for raw
correlation/cointegration strength directly, which would distinguish "regime-context adds real
information" from "both tests just detect the same thing."

**Price-target pairs-relative overlay — an honest negative result, matching Finding #57's
confidence-score pattern.** `research/price_target_pairs_overlay.py`: for each of this project's
own 1,340 real trades (`baseline_trades_layer1.parquet`), computes each leg's own causal,
staleness-gated (120-day cutoff) analyst-implied return to target, then the RELATIVE divergence
between legs, and whether the trade's actual direction (backtest.py's own `side` convention: long
= long A/short B) agrees or disagrees with that divergence. `debug/_verify_price_target_pairs_
overlay.py` (11/11) caught a real bug live before trusting the real-data run: `agrees_with_
consensus` is an object-dtype column (True/False/None), and `~` on an object Series does Python
bitwise NOT (`~True == -2`), not boolean negation — `disagree = scored[~scored["agrees_with_
consensus"]]` crashed with a KeyError trying to select columns named -2/-1 instead of negating a
mask. Fixed by casting to real `bool` dtype before negating; a new verify check specifically
reproduces this exact failure mode to guard against a regression. **Real result on 1,191/1,340
scored trades (89% coverage)**: agrees-with-consensus trades show $135.07 mean P&L / 60.99% win
rate (n=546) vs. disagrees' $141.49 / 62.64% (n=645) — no meaningful difference, and if anything
the wrong-sign direction (Welch's t=-0.33, p=0.74). An honest negative result: this specific
pairs-relative construction of analyst-target divergence does not predict this project's own
trade P&L.

Files: `research/transfer_entropy_lead_lag.py` (`summarize_pair_for_ml`), `ml.py` (2 new
features), `debug/_verify_transfer_entropy_lead_lag.py` (10/10), `research/pit_confirmation_vs_
regime_interaction.py` (new), `debug/_verify_pit_confirmation_vs_regime_interaction.py` (new,
8/8), `research/price_target_pairs_overlay.py` (new), `debug/_verify_price_target_pairs_
overlay.py` (new, 11/11), `output/research/transfer_entropy_pair_summary.parquet`,
`output/research/pit_confirmation_vs_regime_interaction.parquet`, `output/research/price_target_
pairs_overlay.parquet` (all new).

## 66. The Caveat/Limitation Search's Tier A Items — All Real, Genuine Results, Two Real Bugs
Found in the Process, One Surprisingly-Already-Solved Item

Ross asked for a systematic caveat/limitation search across both papers, then approved working
through all three resulting tiers (A: cheap/tractable now; B: real new work but feasible; C:
structural, narrow-not-eliminate). Tier A's five items:

**§7.1 BH-vs-Benjamini-Yekutieli at true full-universe scale (Tier B item #8, done alongside
Tier A given the infrastructure work overlapped)**: `research/bh_vs_by_full_universe_1d.py`
(new) reuses the ALREADY-COMPUTED full-universe Pearson prefilter (997,024 real candidate pairs,
10-year/1D lookback) instead of redoing that O(n²) step — the actual intractable part the
original N=300-sample script's docstring named. **Two real bugs found and fixed before trusting
any result**: (1) a tz-naive/tz-aware mismatch crash — the exact known bug class
`pit_wfa_wrds_daily.py` already fixed once (Binance crypto tz-aware vs. everything else
tz-naive), same fix applied here; (2) a more consequential one — using
`DataAligner.align_universe` instead of `universe_loader.align_to_common_calendar` silently
produced per-symbol-length arrays (e.g. a real pair, AA: 2,304 rows from 2016 vs. DOW: 1,698 rows
from 2019), which `_eg_worker`'s positional isfinite-mask can't handle; its own try/except
silently swallowed the resulting broadcast error as "not ok" rather than crashing loudly — a
smoke test (5/200 usable results) caught it before the real 30,000-pair run, not after.
`align_to_common_calendar` is the SAME fix this project already diagnosed once (2026-08-14,
`universe_loader.py`'s own docstring) for exactly this scenario — reused, not rediscovered,
confirming a real, disclosed synthetic proof
(`debug/_verify_bh_vs_by_full_universe_1d.py`, 4/4) before the full run. **Real result on
29,890/30,000 usable pairs**: 2,518 raw-significant (p<0.05), BH confirms 35, BY confirms 23 — a
genuine 12-pair gap between the two corrections, the honest, full-scale answer §7.1 needed.

**§4's negative-backtest extended to the current 29-pair confirmed set (Tier A item #3)**:
`pit_wfa.py --variant both`, a straightforward re-run (no code changes — the script already
re-derives pair selection per fold from train-window data, so it naturally reflects whatever the
current universe supports). Real result: fold1 (both variants) still finds 0 PIT-confirmed pairs;
fold2_exp: 3 confirmed/3 traded/28 trades, Sharpe **+0.3486**; fold2_roll: 49 confirmed/17
traded/288 trades, Sharpe **-0.4548**. Same qualitative pattern already established throughout
this paper (fold-to-fold sign disagreement) — a fresh, current-universe confirmation of the
existing finding, not a new story.

**7 non-PIT-safe comparison arms re-pointed at PIT-safe pairs (Tier A item #6) — turned out to
be a re-run, not a code-writing task**: all 7 scripts (`cycle_detection.py`, `levy_jump_
diffusion.py`, `rough_volatility.py`, `options_greeks_features.py`, `svm_gradient_descent_
classifier.py`, `inverse_polarity.py`, `trig_convergence.py`) already had a working `--pit-safe`
CLI flag built in from when the gap was first disclosed (§7.17) — the "top open priority" was
always just running them with it, not building anything new. All 7 completed: cycle_detection
went from a handful of pairs to 132 real rows; options_greeks_features produced multi-pair output
(vs. the original KVUE/KMB-only run); **levy_jump_diffusion's 0%-overlap-with-GapFlag finding
robustly replicated at much larger PIT-safe scale**, strengthening rather than contradicting the
original claim; **inverse_polarity's honest negative (0 genuine polar-opposite candidates) also
replicated** on the wider pair set; trig_convergence produced real multi-pair output (vs. the
original small set); rough_volatility scaled from a handful of symbols to 1,858 real rows
(`h_rs`/`h_dfa`/`h_wavelet` per symbol) — consistent with the original "mixed, window-dependent"
characterization, not a reversal.

**§5's survivorship-of-crisis-pairs confound (Tier A item #2)**:
`research/crisis_regime_survivorship_confound_test.py` (new) joins the crisis-regime diagnostic
against `sp500_membership_history.parquet` via permno. Real, disclosed scope limit stated before
running anything: only 20.6% of the 638,095-pair universe (131,362 pairs) has both legs
S&P-500-trackable at all — the same WRDS-subscription limit already established (no equivalent
point-in-time product for S&P 400/600). **Within that trackable subset**: confirmation rate is
0.34% for pairs where both legs survived to present vs. 0.30% where at least one leg was
delisted — not statistically different (z=1.26, p=0.21). A real, honest, partial answer: no
strong survivorship confound detected in the part of the universe this WRDS subscription can
actually measure; the other 79% remains genuinely unknown, not assumed clean.

**§4's regime-strength segmentation vs. PIT-confirmation precision (Tier A item #7)**:
`research/regime_strength_vs_pit_confirmation.py` (new), reusing `pit_confirmation_vs_regime_
interaction.py`'s exact join machinery, predictor column swapped from `first_regime` to
`strength`. **Striking, clean result**: all 16 pairs overlapping between the regime-strength
universe and §4's PIT-confirmed set are "strong," zero from "moderate" or "weak" (z=3.98,
p=0.0001) — a real, statistically decisive, and intuitively sensible finding (regime-context
strength predicts independent PIT survival), though the same shared-underlying-correlation-
strength caveat already disclosed for the §4/§5 interaction result (Finding #65) applies here
too.

**§5's residual-correlation-factor split under cluster-robust treatment (Tier A item #1)**:
`research/residual_correlation_cluster_bootstrap_test.py` (new), reusing `crisis_regime_
cluster_bootstrap_test.py`'s `cluster_bootstrap_confirmation_rate` unchanged. **Real, honest
scope-narrowing finding, not what was originally assumed**: of the 929 total §5-confirmed pairs,
only 44 are BOTH crisis-first AND assignable to one of the 12 known crisis episodes (885 are
calm-first or otherwise unassignable) — meaning the original "6.7% survives factor-adjustment"
figure spans a different, broader population (all 929 confirmed pairs) than what a crisis-episode
cluster bootstrap can test. On the narrower, crisis-episode-assignable 44-pair subset: observed
survives-residual-correlation rate is 31.8% (notably higher than the full population's 6.7%), with a
WIDE cluster-bootstrap 95% CI of [11.6%, 46.4%] — genuine, disclosed uncertainty at this small
episode-clustered sample size, not a precise number to lean on.

Files: `research/bh_vs_by_full_universe_1d.py` (new), `debug/_verify_bh_vs_by_full_universe_1d.py`
(new, 4/4), `research/crisis_regime_survivorship_confound_test.py` (new), `research/regime_
strength_vs_pit_confirmation.py` (new), `research/residual_correlation_cluster_bootstrap_test.py`
(new), `output/backtest/pit_wfa_{fold_comparison,portfolio,pair_sets}.parquet` (re-run, 29-pair
era), `output/research/{bh_vs_by_full_universe_1d_raw,bh_vs_by_full_universe_1d_summary,crisis_
regime_survivorship_confound_test,regime_strength_vs_pit_confirmation,residual_correlation_
cluster_bootstrap,cycle_detection,levy_jump_diffusion,options_greeks_features_*}.parquet` (new/
updated, PIT-safe reruns).

## 67. Free Alternatives to Two "Paid Data" Blockers (SPAC Universe, Crowding Proxy), and a Real
Git Reconciliation That Turned Out to Be Almost Entirely Cosmetic

Ross asked to work the remaining "blocked" items from the caveat search, specifically: "if we
can't [use paywalled data] can we scrape data or use related data?" Both Tier B items flagged as
needing a paid source turned out to have real, free, government-mandated-disclosure alternatives
— found by checking, not assumed.

**§7.3's SPAC-regex limitation — `data_sec_edgar.py` (new)**: SEC EDGAR classifies blank-check
companies under SIC code 6770, filterable directly via EDGAR's own free company-search endpoint
— no paid tracker needed. **Real bug caught and fixed live**: SEC's own legacy `output=atom`
endpoint has a confirmed, longstanding bug where the `<entry title>` and `<company-info name>`
fields both contain the literal broken Perl stringification `ARRAY(0x...)` instead of the real
company name — verified directly against a raw response, not assumed from documentation. Worked
around by using only the reliable `<cik>` element from that feed, then getting real company names
and tickers from SEC's separate, working `company_tickers.json` endpoint. A second bug (CIK
representation mismatch — zero-padded string vs. plain int between the two sources) was caught
via `debug/_verify_data_sec_edgar.py` (3/3) before trusting the join. **Real result**: 3,329
distinct SIC=6770 companies found, 933 with a registered ticker. Cross-referenced against this
project's own universe: the existing regex-based `spac_symbols.json` had only 23 symbols, of
which just **1** overlaps with the new SEC-based list — the two approaches largely find
*different* symbols (SEC's registered tickers often carry unit/warrant suffixes like `AACIU`/
`AACIW` that don't match CRSP's own symbol convention, a real, disclosed mismatch, not glossed
over). Checked directly for double-counting before reporting a coverage number: all 95 SEC-based
tickers found in this project's universe map to 95 genuinely distinct base tickers, not
unit/warrant duplicates of already-known symbols — a real, clean ~4x coverage improvement (95 vs.
23), not an artifact.

**Crowding/capacity-decay's "needs paid flow data" blocker — `data_finra.py` (new)**: FINRA
publishes biweekly equity short interest per security, free, no authentication, covering ALL
exchanges (confirmed directly against a live file — NYSE-listed "A"/Agilent and "AA"/Alcoa both
present with real short-interest figures, despite the URL's `otcmarket` path component suggesting
OTC-only coverage). `debug/_verify_data_finra.py` (5/5, mocked to avoid depending on live network
access for the test itself) confirms the caching behavior. Real result: 22,482 securities in one
settlement-date file, with `currentShortPositionQuantity`/`daysToCoverQuantity`/`changePercent`
fields — a genuine, free crowding proxy. Neither this nor the SPAC list has been WIRED into any
actual analysis yet this session (that's the natural next step, not done here) — both are
confirmed-working, real data sources ready to use.

**A large git-reconciliation scare that resolved to almost nothing real**: investigating
CachyOS's ~115 "genuinely different" tracked files (flagged as a real risk in the prior entry)
found the root cause was CRLF vs. LF line-ending representation, not real content divergence —
`git diff analysis.py` showed 13,134 changed lines, but after adding `.gitattributes` (`* text=auto
eol=lf`) and running `git add --renormalize .`, **every one of those files showed ZERO real
diff**. The only genuine content was ~67 CachyOS-only Python scripts (GPU-backend/polars work,
episodic-scan auto-restart tooling) that had simply never been committed, plus one real, small
merge conflict (`options_greeks_features.py`, resolved by keeping the already-verified upstream
dedup fix from earlier tonight) and a handful of tracked log files (resolved by taking CachyOS's
own local state — low-stakes, informational only). Both machines are now on the identical commit
(`9aae6b8e` at reconciliation time), confirmed via `git status` showing clean (non-log) on both
sides — pushed via a properly-scoped bundle (`git bundle create ... origin/main..main`, not a
bare `git bundle create ... main`, which the first attempt got wrong and produced a 3.5GB
whole-history bundle instead of a ~99KB incremental one) since CachyOS has no GitHub push
credentials configured.

Files: `data_sec_edgar.py` (new), `debug/_verify_data_sec_edgar.py` (new, 3/3), `data_finra.py`
(new), `debug/_verify_data_finra.py` (new, 5/5), `output/cache/sec_edgar/spac_universe_sic6770.
parquet` (new), `output/cache/finra/short_interest_20260814.parquet` (new), `.gitattributes`
(new), `.gitignore` (episodic-scan retry-log noise excluded).
