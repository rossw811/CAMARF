# Grand Sweep Bug/Correctness Audit — 2026-07-20

Full-codebase read-only audit per Ross's directive (dedicated_pass.md §11, itself triggered by the
pair-set collapse investigation): "deploy improve or code review agents... do a full bug sweep." Covers
all 90 `research/*.py` scripts (7 sequential batches) plus all remaining production files (1 batch), on
top of two items already fixed/investigated directly this session (BUG-D70, the EG gap-contamination
investigation). One agent at a time throughout, per this project's standing rule.

**A key refinement emerged mid-sweep** (see "Refined risk classification" below) that re-shapes how
several findings should be read — noted inline wherever it applies.

This document is the master list for the discussion Ross asked for after the sweep completed. Nothing
here has been fixed yet except BUG-D70 (already applied) — this is the input to that discussion, not a
completed action log.

---

## Refined risk classification (learned mid-sweep, applies throughout)

A "drop DATA_GAP-masked rows via `.dropna()`/boolean-mask, then do a positional `np.diff`/`.shift()`/lag
operation" pattern was initially flagged as universally risky. Real-data investigation (see "EG
gap-contamination investigation" below) found:

- **LOW risk — cointegration/ADF/level-based tests** (EG test, Johansen, KPSS, VECM-based exogeneity):
  bridging a routine overnight/weekend/holiday closure is standard, defensible practice — these tests
  don't hinge on each "lag" representing identical wall-clock time. Measured directly: for the 19 symbols
  driving the current pair-set investigation, every `GapFlag.DATA_GAP` run is 17-93 bars (routine
  closures), zero genuine multi-day outages found.
- **HIGH concern — lag-sensitive tests** (variance-ratio, autocorrelation, half-life, entropy,
  jump-detection/jump-intensity, asymmetry/leverage tests on consecutive deltas, lag-1 cross-covariance):
  these specifically depend on "lag k" meaning a fixed real elapsed time. Silently folding a weekend into
  "1 lag" is a genuine, more defensible concern here.

Findings below are tagged `[LOW-risk mechanism]` or `[HIGH-concern mechanism]` where this classification
applies. Batch 4's findings were made *before* this refinement was learned (mid-way through batch 4→5) —
they are re-tagged retroactively in this document, not as originally reported.

---

## TIER 1 — Headline-affecting production bugs

These directly touch numbers currently cited in CLAUDE.md/PAPER.md/Development.md, or the core
confirmed-pair screening mechanism.

### 1.1 `backtest.py` — risk-parity/HRP/pnl-cap sizing weights fit on a window overlapping their own OOS evaluation window
**Not previously logged.** `compute_risk_parity_weights()`, `compute_hrp_weights()`, `compute_pnl_cap_thresholds()`
(lines 1083-1338) default to `is_trades_path="output/backtest/trades_layer1.parquet"` — a **full-series**
(100%-of-history) run per the module's own docstring, which necessarily contains the same trailing-20%
window a subsequent `--holdout --risk-parity` run treats as "OOS." Per-pair volatility used to size an OOS
trade is therefore partly computed from that same trade's own P&L — real in-sample circularity, not
documented anywhere currently. Directly touches the "recommended production" claim (risk-parity OOS
Sharpe 5.8689).

### 1.2 `wfa.py` — hardcoded strategy constants have drifted from `Config.BACKTEST`, despite a comment claiming they match
**Not previously logged.** Three constants (lines 73-80) diverge: `EXIT_ZSCORE` (0.5 here vs. 0.0 in
config), `SLIPPAGE_BPS` (2.0 vs. 5), `MAX_HOLD_MULT` (3.0 vs. `MAX_HOLD_MULTIPLIER`=2.0). The WFA Sharpe
figures already cited in CLAUDE.md/PAPER.md ("baseline expanding/rolling 3.13/3.27; mm_exec 3.82/3.96")
are computed from a materially different strategy than backtest.py's own headline OOS Sharpe (5.24),
despite being presented side-by-side as a robustness check of the *same* strategy.

### 1.3 `run_storm_grid.py` — direct recurrence of the BUG-D62/D64/D70 Sharpe-pooling bug, previously missed
`portfolio_sharpe()` (line 68) uses `groupby("date")["pnl_net"].sum()` instead of the `resample("1D")`
zero-fill convention `portfolio_math.py` now centralizes. Inflates every Sharpe in the 16-combination
STORM factor grid and its "marginal effect of each factor" table. Ironically imports `BacktestEngine`
directly from backtest.py (good reuse) but reimplements portfolio aggregation from scratch instead of
reusing `aggregate_portfolio()`/`portfolio_math.py`.

### 1.4 `data_ibkr.py` — recurrence of BUG-D65's split-adjustment-seam bug in an uncovered merge path
`merge_with_yfinance()` (lines 130-166) does its own hand-rolled `pd.concat([ibkr_hist, yf_df])` merge
with zero split-adjustment reconciliation — the exact bug class BUG-D65 fixed via
`DataStore._reconcile_split_adjustment()`, but that fix covers "all 13 existing call sites" and this is a
14th, independent path never wired in. Notable because this file's stated purpose is specifically
survivorship-bias/episodic-cointegration testing on long-window deep history — exactly what a silent
seam artifact would corrupt by masquerading as a structural break.

### 1.5 BUG-D70 — Sharpe-pooling bug in 6 files — **already fixed and verified this session**
`deflated_sharpe.py` (feeds headline DSR), `stats.py`'s permutation test, `cvar.py`, `fresh_holdout_compare.py`.
Shared `portfolio_math.py` utility built, all 4 migrated, synthetic + real-data verification passed.
Real-data delta on cached OOS trades: DSR 0.0020→0.0000 (both near-zero; conclusion unchanged, corrected
number is honestly lower). Full write-up: Development.md, "BUG-D70." **Deliberately NOT migrated** (need
their own review, different question — see Tier 3): `stats.py::_build_daily_pnl()`,
`research/portfolio_effective_bets.py`, `research/return_smoothing_audit.py`.

---

## TIER 2 — Real bugs in research scripts with direct bearing on active investigations

### 2.1 `lag_aware_cointegration_discovery.py` — confirmed LIVE bug, not just risk
Its read path for `near_miss_lag_scan_{args.tf}.parquet` uses the raw `args.tf` label, but
`near_miss_lag_scan.py` (BUG-D67's fix) writes monthly TFs under remapped safe names (`1mo`/`3mo`/`6mo`).
Running `--tf 1M` here would silently load minute-granularity data as if it were monthly — the D67 fix
exists in the codebase but was never propagated to this consumer.

### 2.2 `comomentum.py` — recurs a lookahead bug `analysis.py` already fixed once in `backtest.py`
Uses the full-sample scalar `hedge_ratio_ols` field instead of the already-available point-in-time
`hedge_ratio_ols_t` series — `analysis.py`'s own comments (~line 4865-4868) document exactly why the
scalar version was replaced. `ml.py`'s `hedge_ratio_drift` feature (Tier 3) has the identical defect,
independently.

### 2.3 `earnings_lead_lag.py` → `big_move_lead_lag.py` — pooled-window seam contamination `[HIGH-concern mechanism]`
Both pool disjoint event windows into one series, then do a positional `.shift()` that silently pairs
one window's tail with an unrelated window's head as if temporally adjacent — contaminates the
non-zero-lag test specifically. `big_move_lead_lag.py` explicitly copies `earnings_lead_lag.py`'s
structure verbatim, so this is the same bug in both, not independently discovered twice.

### 2.4 `follower_direction_validation.py` — mislabeled OOS, real statistical validity bug
Computes overlapping expanding-window OLS betas (no genuine held-out prediction despite the "OOS" label),
then treats those heavily-correlated estimates as independent samples in a standard-error calculation —
manufactures artificially significant t-stats for almost any pair with even weak real beta. BH-FDR
downstream can't fix already-invalid p-values.

### 2.5 `leg_level_early_exit.py` — full-sample non-causal hedge ratio (lookahead)
Single full-sample OLS hedge ratio applied to build the z-score for every historical bar's simulated
entry/exit — every reported PnL/Sharpe-like number is not a valid causal backtest. **Confirmed origin**:
`breakout_vs_reversion.py::build_spread_and_z` (honestly disclosed there as non-tradeable), now copy-pasted
into 4 total files (see Tier 4, item 4.1).

### 2.6 `jump_diffusion_spread_analysis.py` → `jump_diffusion_parameter_fit.py` `[HIGH-concern mechanism]`
Both drop DATA_GAP rows then `np.diff()` for jump-detection — a dropped multi-day gap is indistinguishable
from a genuine single-bar jump to the Merton MLE. `parameter_fit.py` is an explicit extension of
`spread_analysis.py` and inherited the bug forward. Also corrupts `spread_analysis.py`'s own
near-jump-vs-calm trade-outcome comparison.

### 2.7 `predictability_optimizer.py` `[HIGH-concern mechanism]` — most consequential of the entropy/regime-family findings
Drop-then-diff contaminates the lag-1 cross-covariance matrix behind its own headline IS/OOS
predictability-ratio comparison. `ccp_variants.py` (2.8) imports this same function and inherits the issue.

### 2.8 `ccp_variants.py` `[HIGH-concern mechanism]` + a distinct verification-methodology gap
Same lag-1 cross-covariance contamination (via `predictability_optimizer.py`). Separately notable: its own
synthetic `_verify()` uses purely gapless synthetic arrays, so it structurally cannot catch this
real-data-specific failure mode — worth naming as its own pattern (a verification test that can't detect
the exact bug class it should).

### 2.9 `variance_ratio_test.py` `[HIGH-concern mechanism, but re-assessed]`
Originally flagged as severe (its docstring's own "83% of rows are padding" figure for AMD/DD@1h read as
alarming). Re-assessed after measurement: `(26067 total - 4452 real)/26067 ≈ 82.9%` is the **normal,
universal** padding ratio from `align_intraday`'s calendar-time dense reindex, not evidence of an
anomalous gap specific to that pair. The underlying mechanism concern (lag-k assumes uniform spacing)
still applies to this test type per the refined classification — but the specific "83%" figure is not
itself alarming.

### 2.10 `network_momentum.py` `[HIGH-concern mechanism]`
`.fillna(0.0)` on a returns panel with real (not gap-related) missing-data NaNs distorts a lag-1
cross-correlation, especially for thinner/newer symbols. Self-disclosed as "a signal-existence test, not a
backtest," which limits but doesn't eliminate the concern.

### 2.11 `news_impact_asymmetry.py` `[HIGH-concern mechanism]`
Borrows its gap-masking justification from `threshold_cointegration.py`'s docstring, but that script's
rationale is specifically about a level-based test — doesn't actually transfer to this lag-1-diff-based
asymmetry test. Good concrete case for why the test-type distinction matters in practice.

### 2.12 `peer_correlation_contamination_check.py` `[HIGH-concern mechanism]`
No gap-flag check on the prior bar when computing a same-day return — ironic since this script exists
specifically to validate symbols already flagged as data-quality-suspect, i.e. exactly the population most
likely to have a stale forward-filled anchor.

### 2.13 `dd_hub_effective_bets.py` `[HIGH-concern mechanism]`
Each pair's DATA_GAP rows are dropped independently before an intersection-then-diff step — because gap
timestamps differ per pair, the final intersection can drop rows asymmetrically, so some pairs' diffs
silently span more than one nominal bar while siblings' don't, at the same row.

---

## TIER 3 — Point-in-time/lookahead and in-sample-circularity bugs (methodology, not data-quality)

### 3.1 `ml.py` — median imputation computed over the full dataset before train/val/test split
`_train_and_validate()` line 601: `X = df[_FEATURE_COLS].fillna(df[_FEATURE_COLS].median())` — val/test
values leak into the median used to fill training-set NaNs. Should fit on `X_train` only.

### 3.2 `ml.py` — `hedge_ratio_drift` uses static scalar fields, not the point-in-time series
Same defect class as `comomentum.py` (2.2). Mirrored identically in `backtest.py`'s Layer-2 ML-gate
features (`_ml_hedge_drift`) — same bug in both training and serving code, so no train/serve skew, but
both need fixing together. **Currently inert**: `LAYER2_ENABLED=False`.

### 3.3 In-sample circularity — fit-and-score-on-the-same-panel, found independently in 5 files
- `eigenvalue_weighted_position_sizing.py` — weights + MP-adaptive `top_k` fit on the full IS+OOS panel,
  Sharpe scored on that same panel.
- `portfolio_position_sizing_correction.py` — same pattern (ERC weights, cluster labels).
- `convex_portfolio_construction.py` — **starkest instance**: the SLSQP objective function literally *is*
  the reported metric, on the same sample.
- `caviar_dynamic_var.py` — same shape, but **honestly disclosed** (docstring states it mirrors
  `cvar.py::historical_cvar`'s existing in-sample convention, not claimed as OOS).
- `quantile_regression_forest.py` — same shape, **honestly labeled** "in-sample" in its own output; likely
  gated behind a data-sufficiency floor not yet cleared on real data.
- `decoupling_backtest.py` — backtests re-qualified pairs on the same post-break window used to select
  them — **honestly disclosed** in its own log output.
- Good template for the fix: `k_bahc_covariance_cleaning.py` does genuine walk-forward (train-window fit,
  following-window realized-variance evaluation).

### 3.4 Full-sample non-causal OLS hedge-ratio helper — copy-pasted into 4 files, no shared function
Origin: `breakout_vs_reversion.py::build_spread_and_z` (honestly disclosed there). Independently
copy-pasted into `leg_level_early_exit.py` (2.5), `archetype_conditional_sizing.py`,
`vol_targeting_and_drawdown_derisking.py`, `hub_leg_stop_conditioning.py`. None call a shared function —
a future fix to one won't propagate to the others (same shape as BUG-D62→D64, BUG-D65→D66).

### 3.5 `vol_targeting_and_drawdown_derisking.py` — second, distinct lookahead in the same file
Beyond 3.4's shared helper: `target_vol` is a full-history median of trailing vol, used to size every
trade across the whole series — an early trade's size depends on a target informed by years-later data.
(The drawdown-derisking arm in the same file is correctly causal.)

### 3.6 `backtest.py::_cf_carver` — full-sample scale factor in a STORM comparison arm
`_avg_abs_entry_z` computed once from the entire `df` passed to `run()`, applied as a constant multiplier
throughout. Not gated behind any production default — a comparison-arm-only issue currently.

---

## TIER 4 — Statistical validity (independence violations, multiple-comparisons, BUG-D59-class)

### 4.1 BUG-D59-class ("unweighted mean of per-pair Sharpes" instead of pooled portfolio Sharpe) — recurs twice
- `fill_timing_sensitivity.py` — unqualified, feeds the script's own headline "% Sharpe degradation" claim.
- `breakout_vs_reversion.py` — only in `main()`'s top-level aggregate; the same file's
  `run_combination_sweep()` a few dozen lines earlier correctly pools first, specifically to avoid this
  exact trap — a clean illustration of BUG-D69's lesson (avoiding a bug in one code path doesn't guarantee
  a sibling path in the same file does too).
- Good template: `capital_sim_selection_mechanism.py` explicitly checked its pooling against
  `aggregate_portfolio()`.

### 4.2 Correlated observations treated as independent
- `earnings_structural_break_correlation.py` — pools break events across pairs/timeframes as independent
  Bernoulli trials, but many share DD as a leg (73.4% of the 1h candidate pool per `trend_dominance_diagnostic.py`)
  — inflates effective N. Also: 3 window sizes tested with no multiple-comparisons correction.
- `short_term_factor_alpha.py` — the seasonality (Monday) signal is literally identical across every asset
  on a given day, so its true independent information content is ~n_days, not n_days×n_assets; `n_obs`
  reports the latter.
- `decay_proxy.py` — 80%-overlapping rolling windows (15-trade window, step 3) treated as independent
  draws for a z-score's standard deviation — understates true variance, makes the decay-detection test
  more trigger-happy than its `_Z_THRESHOLD=-2.0` implies. Review-flag diagnostic only, not an exclusion rule.
- `eg_permutation_check.py` — subtler: the set of masked positions differs by shift amount on every
  permutation draw (since NaNs still carry through `np.roll`), while the real-data p-value uses one fixed
  contamination pattern — real-vs-null isn't quite apples-to-apples on this dimension.

---

## TIER 5 — Recurring D67/A14-class Windows path collisions (raw tf-label in output filename)

Confirmed in: `audit_price_degeneracy.py`, `price_density_screen.py` (×2, plus an incomplete `_TF_SAFE`
duplicate missing 5 mappings), `lead_lag_permutation_check.py`, `lag_sweep_validation.py`,
`lag_aware_cointegration_discovery.py` (own outputs), `big_move_lead_lag.py`, `earnings_lead_lag.py`,
`leg_level_early_exit.py`, `relational_regime_indicator.py`, `wavelet_hurst_comparison.py`,
`graph_clustering.py` (writes raw despite reading through `_TF_SAFE` one line above),
`coint_frac_window_grid.py` (related: no tf-suffix at all in its output path, silently overwrites across
timeframes rather than colliding on case). All isolated to research output, none touch production cache.
Same class as BUG-D67/A14, ~11 new instances.

---

## TIER 6 — Silent exception swallowing / doc-drift / minor findings

- `lead_lag_scan.py::_eg_pvalue()` — bare `except Exception: return None` with no logging, shared by 7
  files that reuse it.
- `adf_confirmatory_tier.py` — exception text captured then discarded; saved parquet can't distinguish
  "ADF errored" from "ADF ran, found nothing."
- `regime_cluster_robustness_check.py`, `rmt_feature_denoising.py` — bare excepts in bootstrap/example
  loops, no logging of what failed.
- `data_contamination_scan.py` — wrong (but currently inert) assumption about the confirmed-pairs manifest
  schema; separately, a cosmetic sign-loss bug in a console print (doesn't touch saved data).
- `regime_conditional_analysis.py` — docstring claims a Welch t-test that doesn't exist anywhere in the code.
- `cross_timeframe_divergence.py` — docstring/usage example references a CLI flag `main()` never registers.
- `bias_budget.py` — a hardcoded, static "378 delist events excluded" figure that will silently go stale,
  ironic given the script's entire purpose is an honest, current bias ledger.
- `decoupling_requalification.py`, `stress_test_replication.py` `[LOW-risk mechanism]` — no gap-flag
  masking at all before their EG tests (worse practice than bridging, since it's an unmasked forward-fill
  artifact) — low risk given the test type, but worth aligning with sibling scripts that do mask correctly.
- `filter_ablation.py` — a real subprocess crash and "legitimately zero trades" collapse to the same `{}}`
  return; distinguishable in console output but not in the saved parquet.
- `config.py` — confirms BUG-D60 (`MAX_CONCENTRATION_PCT`/`ACCOUNT_SIZES` unused) and additionally
  several more dead/aspirational fields (`SIZING_METHODS`, `COARSE_*`, `FINE_GRID_*`, `WFA_N_WINDOWS`/`TRAIN_PCT`/`TEST_PCT`,
  `DAILY_LOSS_LIMIT_PCT`, `CONSECUTIVE_LOSS_LIMIT`) that no current script reads.
- `backtest.py` line 445 — `df[df["z_rolling"] != 0.0]` drops genuine mid-series exact-zero crossings
  along with warmup bars, could delay a signal exit by one bar. Edge case.

---

## Investigated and closed with a negative result (this session)

**EG gap-contamination in `analysis.py`'s `_eg_worker`/`_rolling_coint_worker`.** Attempted a
`_longest_finite_run` fix; synthetic verification passed but real-data testing collapsed every pair's
overlap to ~6 bars (catastrophic regression) — root-caused to `align_intraday`'s calendar-time dense
reindex classifying every routine overnight/weekend closure as `GapFlag.DATA_GAP`, same code used for
genuine outages. Reverted (confirmed byte-identical to last commit). Follow-up measurement: all 19
symbols driving the current pair-set investigation have DATA_GAP runs of 17-93 bars only (routine
closures) — **zero genuine anomalous outages, this mechanism does not currently affect any relevant pair's
EG p-value.** Full chain in Development.md, "Attempted and reverted: gap-aware longest-contiguous-run fix."
Still open (not urgent): no structural safeguard exists if a genuinely anomalous gap ever does occur
somewhere in the wider ~1,600-symbol universe.

---

## Good patterns confirmed clean / worth using as templates

`k_bahc_covariance_cleaning.py` (genuine walk-forward), `capital_sim_selection_mechanism.py` (pooling
checked against the reference implementation), `stop_loss_correlation_caps.py` (correct resample("1D")
convention, independently implemented), `ml_lookahead_selftest.py` (a real, working lookahead-detection
tool with its own documented prior design failure), `pair_characteristics_analyzer.py` (legitimate fresh
chronological split), `trend_dominance_diagnostic.py` (exemplary self-disclosure of its own two-stage
design's validation limits), `copula_pairs.py` (genuine expanding-window walk-forward),
`hmm_gmm_regime_trade_features.py` (discloses its own full-sample-fit limitation and built a real
stability check for it), `_regime_features.py`/`regime_conditional_entry_gate.py` (never drop rows before
diffing — the correct reference pattern for the entropy/regime family).

---

## Cross-cutting patterns worth a project-wide decision, not a per-file fix

1. **"Same bug fixed in one file, not propagated to a sibling/consumer"** recurs far more than the two
   instances (D62→D64, D65→D66) already logged before this sweep — confirmed again in: `comomentum.py`
   (hedge_ratio_ols_t fix not reused), `lag_aware_cointegration_discovery.py` (D67 fix's read-side not
   updated), `run_storm_grid.py` (portfolio_math.py fix not reused), `data_ibkr.py` (BUG-D65 fix's merge
   path not covered), 4× the full-sample-hedge-ratio helper (3.4), 2× BUG-D59-class (4.1). This is a
   structural, recurring failure mode of "fix the instance, not the class" — worth its own discussion.
2. **Two different, uncoordinated answers to "what do you do with a masked/missing bar before a
   lag-sensitive calculation"**: `dd_hub_effective_bets.py`'s drop-then-diff-across-gaps vs.
   `network_momentum.py`'s fillna(0.0)-for-missing-days — both wrong in different ways, no shared
   convention.
3. Given portfolio_math.py's existence now, several files not touched by BUG-D70 (research/portfolio_effective_bets.py,
   research/return_smoothing_audit.py, stats.py::_build_daily_pnl(), run_storm_grid.py) are candidates for
   migration, but the wide per-pair-panel ones need their own design decision first (calendar zero-fill may
   not be the right convention for a correlation matrix — see BUG-D70's write-up).
