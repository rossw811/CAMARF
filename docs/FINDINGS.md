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

## 24. Ridge-Regularized Hedge Ratio — Clean Negative on Full-Sample Estimates, With a Real Scope
Mismatch to the Motivating Hypothesis [2026-08-10]

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
