# CAMARF — Development Reference

Technical reference for ongoing development. Records all architectural decisions,
bug root causes and fixes, documented biases, methodological decisions, and
comprehensive outlines for all planned modules.

**Research context:** This is an institutional-grade academic research paper
targeting transfer committee review and MFE/FE program applications at
Baruch/CUNY, Berkeley, Columbia, and peer institutions. Every methodological
choice is made with academic rigor and reproducibility as the primary constraints.
The standard is professional and institutional — not a class project.

---

## Development Process & AI Tool Disclosure

This project was developed using Claude (Anthropic) as an active coding and
debugging collaborator throughout. This section documents how, honestly, for
anyone evaluating the work.

**Division of labor:**
- Research thesis, methodology selection, and all judgment calls: the author
- Code implementation, debugging, and documentation drafting: AI-assisted,
  directed and reviewed by the author at every step
- Bug diagnosis: collaborative — many bugs in this project's history were
  caught or correctly diagnosed by the author pushing back on an AI-proposed
  explanation that didn't hold up, or by re-verifying an AI claim directly
  against the running code rather than trusting it

**Documented examples of this in practice (shown, not asserted):**
- Session 7's sp600 Wikipedia scraper investigation: a third-party summary of
  diagnostic output claimed a result that was logically inconsistent with the
  actual retry script's structure — caught by requesting the literal raw text
  instead of continuing to theorize from a summary (full account: "Session 7
  Continued" below).
- Session 8: this very document claimed BUG-D31 (shared yfinance session) and
  BUG-D32 (4h session-aligned resample) were fixed in Session 7. Both claims
  were directly tested against the live code at the start of Session 8 and
  found to be false — the described fixes were never actually present. Caught
  by running the actual code against live data rather than trusting the prior
  session's written record. This is exactly why Session 8 treats every
  "documented as fixed" claim in this file as a hypothesis to verify, not a
  fact — see Session 8 below for what else that standard turned up.

**Why this record exists:** the session-by-session bug registry and decision
log in this document were maintained throughout development, not
reconstructed afterward. They serve as a working record of the actual
reasoning process — why HRP and minimum-CVaR are included alongside (not
instead of) tangency/mean-variance optimization specifically as a
fragile-to-robust comparison, why the GapFlag system has six specific codes,
why coint_fraction_rolling exists as a defense against episodic
cointegration — available for review by anyone evaluating this work's depth
of understanding.

A condensed, public-facing version of this disclosure belongs in the paper
and repo README (not duplicating this internal detail): state plainly that
Claude was used as a coding/debugging collaborator throughout, that all
research design choices and judgment calls were the author's, and point to
this file for the full record. Check each target program's (Baruch/Berkeley/
Columbia) actual current application instructions for any required
disclosure format before finalizing that version — institutional AI-tool
policies are fast-moving and shouldn't be assumed from general knowledge.

---

## Architecture Principles

1. **Comprehension before code** — full logic walkthrough before any implementation
2. **Root-cause fixes only** — no bandaid solutions that mask underlying bugs
3. **Single best solution** — one correct approach, implemented completely
4. **Production-ready output** — no fragments, no truncated files
5. **Explicit over assumed** — ambiguities surfaced with direct questions
6. **Firm discipline on parameter changes** — no tuning until statistical thresholds met
7. **Bias-first design** — every methodological choice is evaluated for the bias it introduces before being implemented. BiasAuditLog records every remedy and its residual risk.
8. **Full reproducibility** — all results traceable from raw parquet/JSON outputs without re-running the pipeline

---

## File Inventory

| File | Lines | Status | Purpose |
|------|-------|--------|---------|
| `config.py` | ~120 | ✅ Complete | All configuration parameters |
| `data.py` | ~2100 | ✅ Complete | Data pipeline: IBKR + yfinance hybrid |
| `analysis.py` | ~3250 | ✅ Complete | Analysis pipeline |
| `ml.py` | — | 🔲 Planned | Feature engineering + ML classifier |
| `backtest.py` | — | 🔲 Planned | Walk-forward backtesting |
| `stats.py` | — | 🔲 Planned | Statistical validation + Monte Carlo |
| `options.py` | — | 🔲 Planned | Options overlay pricing |
| `report.py` | — | 🔲 Planned | LaTeX report generation |

---

## Configuration Parameters (config.py)

```python
# Universe
MIN_PEARSON_CORR  = 0.40   # Pre-filter (lowered from 0.60 — filtered all equities at 0.60)

# Analysis
EG_MAX_LAG        = 10     # ADF max lag for Engle-Granger
EG_SIGNIFICANCE   = 0.05
FDR_ALPHA         = 0.05   # Benjamini-Hochberg
JOHANSEN_DET_ORDER = 0     # constant, no trend
JOHANSEN_K_AR_DIFF = 1
JOHANSEN_SIGNIFICANCE = 0.05
TRIO_MAX_CANDIDATES = 50
```

---

## Documented Biases (BiasAuditLog)

Every bias is recorded in `output/results/bias_audit.json` at runtime.

| Bias | Classification | Mechanism | Remedy | Residual Risk |
|------|----------------|-----------|--------|---------------|
| Survivorship | Data | Current S&P 500 only; removed names absent | Documented; CRSP would correct | Historical cointegration overestimated |
| Pearson pre-filter lookahead | Statistical | Full-sample correlation is lookahead-biased | Used as pre-filter only; EG + rolling spread are primary decisions | Pairs missed by full-sample corr excluded |
| Multiple testing | Statistical | ~5% of N pairs expected false positive under H₀ | BH-FDR at α=0.05 per timeframe | Expected FP proportion ≈ 0.05 |
| Rolling window overlap | Statistical | Step=21 EG windows not fully independent | Documented; fraction is diagnostic not confirmatory | Slightly inflated power |
| Regime lookahead | Model | Full-sample regime fit uses future data for labels | Full-sample for descriptive; WFA refit in backtest.py | ML features inherit lookahead; mitigated by WFA |
| Forex triangular arbitrage | Data | EUR.USD ↔ EUR.GBP: mathematical identity | Excluded from primary findings; logged | None — documented as structural |
| Share-class pairs | Data | GOOGL/GOOG, FOXA/FOX: same company | Excluded from primary findings | None — documented as structural |
| 4h bar truncation | Data | NYSE session is 6.5h; last 4h bar is only 2.5h | Documented; both legs experience same truncation | Vol and VWAP features not comparable across bars |
| 8h ≈ 1D | Data | NYSE 6.5h session = one 8h bar per day | Noted as equivalent to 1D; reported separately | Minor — bar labels differ but data is same |
| Kelly lookahead | Model | Kelly fraction derived from full IS period | Half-Kelly; 60+ live trades before updating | Overcalibrated sizing on IS data |
| Intraday cross-asset alignment | Data | Crypto 24/7, equity 9:30-4:00 ET; forward-fill convention | Documented; convention: forward-fill crypto into equity gaps | Non-trading-hours crypto moves enter equity session open |

---

## Bug Registry

### data.py

**BUG-D01: Futures ambiguous contract** — qualifyContracts returns all expiry months. Fix: filter to expiry ≥ today, sort ascending, take first (front month).

**BUG-D02: Forex contract format** — wrong pair ordering in ib.Forex(). Fix: parse symbol as base/quote.

**BUG-D03: OOM on 1m reindex** — `pd.date_range()` allocates 21M rows before size check OOMs. Fix: compute expected rows from timedelta before calling date_range.

**BUG-D04: Holiday gap detection using pandas 'B'** — misses NYSE-specific holidays. Fix: exchange_calendars with NYSE calendar.

**BUG-D05: Warning 2110 infinite reconnect** — IBKR upstream broken; loop ran indefinitely. Fix: `_upstream_broken` flag exits loop immediately.

**BUG-D06: yfinance 1m period "7d" exceeds hard limit** — Yahoo 8-day limit. Fix: period="5d".

**BUG-D07: ADJUSTED_LAST fails weekly/monthly** — not supported for those intervals. Fix: try ADJUSTED_LAST, fall back to TRADES.

**BUG-D08: MultiIndex group_by="ticker" breaks extraction** — ticker at wrong MultiIndex level. Fix: remove group_by, iterate symbols directly.

**BUG-D09: ProgressLogger PermissionError on OneDrive** — OneDrive lock during sync. Fix: catch OSError broadly, fall back to %TEMP%.

**BUG-D10: Cache backfill returning session-only keys** — backfill only checked session dict, missed 5,752 disk files. Fix: iterate all assets × all TFs, load from DataStore.

**BUG-D11: 7D/1M yfinance weekly inconsistency** — yfinance `interval="1wk"` bar boundaries inconsistent across asset classes and don't align to trading-week Friday convention. Fix: remove 7D/1M from yfinance fetch entirely; derive by resampling 1D data with `W-FRI` (Friday-anchored, all bars stamp on Friday close) and `MS` (month-start).

**BUG-D12: period kwarg missing from get_equity_history()** — incremental refresh passed `period="1mo"` but signature didn't accept it. Fix: added `period` parameter, threads through to yf.download() in both primary and retry paths.

**BUG-D13: Completed assets bypass freshness check** — ProgressLogger marks assets complete; resume skips them entirely without checking if daily data is stale. Fix: post-build pass checks `DataStore.needs_refresh()` for all yf assets not refreshed this session; runs incremental fetch on stale ones.

**BUG-D14: Excluded assets in backfill** — backfill loop could load cached parquet files for VLTO/BNY/FDXF if they existed from before exclusion. Fix: check `symbol in exclusions` in backfill loop; excluded symbols never enter `all_data`.

### analysis.py

**BUG-A01: build_returns_matrix equal-length requirement** — dropped 98% of universe. Fix: NaN-pad shorter arrays, use pairwise-complete correlation.

**BUG-A02: Structural pairs in pairs.parquet** — `_save_tf_results` received pre-split `pair_results`. Fix: filter structural pairs before saving.

**BUG-A03: GOOGL/GOOG not detected as structural** — `_SHARE_CLASS_PAIRS` set not populated. Fix: added known share-class pairs.

**BUG-A04: HMM convergence warnings** — fires for any log-likelihood decrease even below tol. Fix: `warnings.filterwarnings` inside HMM fit; n_iter=200, tol=1e-2.

**BUG-A05: OOM guard allocated date_range before checking** — guard was after allocation. Fix: compute expected rows from timedelta before calling `pd.date_range`.

**BUG-A06: Excluded assets could enter analysis via universe.data** — exclusion set not propagated from data.py to analysis.py. Fix: `UniverseResult.exclusion_set` field carries exclusions; `_run_one_tf` checks it before building `tf_data_raw`.

---

## Bar Alignment Audit (All 12 Timeframes)

| TF | Source | Stamp | Session Alignment | Notes |
|----|--------|-------|-------------------|-------|
| 1m | yfinance / IBKR | Minute open | 9:30 AM ET, trading hours | Most equities unavailable; available ones clean |
| 2m | Derived from 1m | Minute open | Same | ✅ Clean |
| 3m | Derived from 1m | Minute open | Same | ✅ Clean |
| 5m | yfinance | 5-min open | 9:30 AM ET | Last bar may be partial (3:55–4:00) |
| 15m | yfinance | 15-min open | 9:30 AM ET | Same partial-last-bar |
| 30m | yfinance | 30-min open | 9:30 AM ET | Same |
| 1h | yfinance | Hour open | 9:30 ET first bar | ✅ Clean — 6 full 1h bars + partial close |
| 4h | IBKR | Session open | 9:30–1:30, 1:30–4:00 | ⚠️ Second bar is 2.5h not 4h; documented bias |
| 8h | IBKR | Session open | 9:30–4:00 (6.5h) | ⚠️ Effectively 1D in NYSE; labeled 8h but one bar/day |
| 1D | yfinance + IBKR | Date | NYSE calendar | ✅ Clean; DataAligner aligns all to NYSE master calendar |
| 7D | **Derived from 1D** | **Friday close** | **W-FRI resample** | ✅ Fixed — previously yfinance 1wk was inconsistent across asset classes |
| 1M | **Derived from 1D** | **Month start** | **MS resample** | ✅ Fixed — derived from clean 1D base |

**Synthetic bars (important future note):** Dollar bars, volume bars, and range bars (Marcos Lopez de Prado, "Advances in Financial Machine Learning") produce statistically more homogeneous observations than time bars because they sample based on market activity rather than the clock. In a 6.5h session, some 15-minute periods have 10× the volume of others — time bars treat them identically. Dollar bars normalize this. For CAMARF v2, constructing synthetic bars from 1m OHLCV would be a significant methodological upgrade. This would require storing 1m data as the primary base and resampling to synthetic bars before cointegration testing. Noted for future work.

---

## Methodological Decisions Locked

### Correlation Pre-Filter (Three Methods)

1. **Pearson** (primary): full-sample, pairwise-complete, NaN-safe
2. **Spearman** (robustness): rank-based, resistant to outlier returns from earnings events
3. **Rolling average** (decay-aware): mean of last 5 × 252-bar Pearson windows; penalizes faded relationships

**dCor** (distance correlation): captures nonlinear dependence; optional (expensive); enabled for 1D only

Confidence tiers:
- **Gold** — all three confirm: primary findings
- **Silver** — two confirm: secondary findings
- **Bronze** — Pearson only: reported with caveat

### Cointegration Hierarchy

Primary: Engle-Granger + BH-FDR  
Planned (stats.py): KPSS + Phillips-Ouliaris as confirmatory

**Gold tier**: EG + KPSS + PO all confirm → primary research findings  
**Silver tier**: two of three → included with notation  
**Bronze tier**: EG only → appendix / robustness check

### Hedge Ratio Methods

| Method | Lookahead | Status | Role |
|--------|-----------|--------|------|
| OLS rolling 252-bar | None | ✅ Implemented | Primary |
| TLS via SVD | Full sample | ✅ Implemented | Comparison |
| Kalman filter (Q/R frozen after 252 bars) | None | ✅ Implemented | Comparison |
| Huber regression | Rolling | 🔲 Planned (stats.py) | Robustness |
| MM estimator | Rolling | 🔲 Planned (stats.py) | Robustness |

### Structural Pair Exclusion

- Forex triangular arbitrage (shared currency leg)
- Same-company share classes: GOOGL/GOOG, FOXA/FOX, BRK.A/BRK.B, NWS/NWSA, BF.A/BF.B, MOG.A/MOG.B, LGF.A/LGF.B, HEI.A/HEI

---

## ml.py — Comprehensive Outline

### Purpose

Supervised multiclass classification of spread resolution outcomes. The ML layer answers: given all observable signals at entry, what is the probability distribution over the four outcome classes? This is the core predictive claim of the thesis.

### Label Construction

**Target variable:** four-class outcome from forward spread resolution

| Class | Condition at N bars ahead | Interpretation |
|-------|--------------------------|----------------|
| `strong_converge` | spread within 0.5σ of long-run mean | Clear mean reversion — high-quality entry |
| `weak_converge` | spread within 1.0σ of mean | Partial reversion |
| `no_move` | spread within 1.5σ (no direction) | Entry had no edge |
| `diverge_further` | spread wider than at entry | Relationship deteriorating |

**Horizon N:** `2 × half_life` bars (pair-adaptive). NTRS↔STT (hl ≈ 13 bars) gets a 26-bar horizon; JNJ↔PG (hl ≈ 70 bars) gets a 140-bar horizon. Same timeframe units — 26 daily bars vs 26 hourly bars are NOT the same calendar time, but they are the same fraction of the pair's characteristic reversion time.

**Bias note:** labels are constructed from forward-looking data. This is the supervised learning target — it IS the lookahead. The training/test split must be time-ordered (no random shuffle). Walk-forward validation is the only valid evaluation approach.

### Feature Set (All Volatility-Standardized)

Spread-level features:
- `zscore` — rolling 252-bar z-score (primary entry signal)
- `zscore_velocity` — change in z-score over last K bars (momentum of the spread)
- `garch_zscore` — GARCH(1,1)-normalized z-score (adaptive to vol clustering)
- `half_life_current` — current rolling half-life estimate (quality signal)
- `hurst_exponent` — H < 0.5 = mean-reverting; continuous quality score
- `realized_skewness` — negative = left-tail risk; feeds Kelly scaling
- `coint_fraction_rolling` — fraction of recent windows showing cointegration
- `half_life_trend` — slope of rolling half-life (positive = decaying relationship)
- `hedge_ratio_drift` — |OLS β - Kalman β| / OLS β (normalized stability signal)

Regime features (from HMM/GMM):
- `regime_prob_meanreverting` — HMM state probability for the mean-reverting regime
- `regime_prob_trending` — HMM state probability for the trending regime
- `regime_prob_highvol` — HMM state probability for the high-vol regime

Volume/microstructure features (cross-leg):
- `cross_leg_rsi_divergence` — standardized RSI_A - RSI_B
- `relative_volume_a`, `relative_volume_b` — each leg vs rolling average
- `amihud_a`, `amihud_b` — illiquidity per leg
- `vwap_deviation_a`, `vwap_deviation_b` — order flow pressure per leg
- `squeeze_indicator_a`, `squeeze_indicator_b` — BB/KC ratio per leg
- `rolling_corr_velocity` — rate of change of 60-bar rolling correlation
- `cvd_proxy_divergence` — CVD difference between legs (order flow imbalance)

Momentum features:
- `tsmom_divergence` — TSMOM_A - TSMOM_B (sign of 12m return × 1/vol, cross-leg difference)
- `ctsmom_rank_divergence` — cross-sectional momentum rank difference
- `factor_desert` — binary: all signal magnitudes simultaneously near zero

**Dimensionality:** ~25 features after correlation filtering (>0.85 pairs dropped)

### Class Imbalance Handling

All three methods tested and compared — paper reports which performs best by OOS calibration:
1. **Natural distribution** — no resampling; model learns class frequencies from data
2. **Class-weight balancing** — `scale_pos_weight` in XGBoost; inverse frequency weighting
3. **SMOTE oversampling** — synthetic minority oversampling in feature space

Report: calibration curves for each method. A well-calibrated probability score (predicted 70% = actual 70% convergence rate) is more valuable than raw accuracy.

### Models (All Three Tested for Comparison)

**Primary:** XGBoost / LightGBM — gradient boosting on tabular data; handles non-linearity, provides SHAP, fast to train and tune.

**Comparison 1:** Random Forest — bagged decision trees; less prone to overfitting than boosting; good baseline for feature importance comparison.

**Comparison 2:** MLP (small neural network, 2 hidden layers) — checks for nonlinear structure that tree models might miss; requires more data and regularization.

The comparison matrix reports all three side-by-side. If MLP offers no improvement over XGBoost, that's a result (tree models are sufficient for this feature set).

### Signal Usage in Strategy

**Architecture:** go/no-go gate with continuous probability scaling

```
Entry decision:
  IF zscore > entry_threshold (e.g. 2.0):
    prob = model.predict_proba(features)["strong_converge"] + 
           0.5 * model.predict_proba(features)["weak_converge"]
    IF prob > go_threshold (e.g. 0.55):
      position_size = base_size × prob   # scale by confidence
    ELSE:
      skip entry (no-go)
```

This means a 0.90-probability entry gets full position; a 0.56-probability entry gets 56% of full position. The go_threshold and the scaling function are themselves parameters subject to sensitivity analysis.

### Walk-Forward Validation

```
Total IS data: all confirmed pair entries
Split: 60% train | 20% validation (hyperparam tuning) | 20% test (touched once)
Step: rolling forward in 6-month increments
Refit: model retrained from scratch at each step (no warm-starting)
```

**PBO Test (Probability of Backtest Overfitting):** combinatorial cross-validation across 16 subperiods. PBO < 0.25 is the threshold for "not overfit." This directly addresses the overfitting concern that any reviewer will raise.

### SHAP Feature Importance

Both computed and reported:
- **Per-pair SHAP:** which features matter most for NTRS↔STT specifically? (e.g., does the half_life trend dominate for custody banks but not for utilities?)
- **Global aggregated SHAP:** ranked feature importance across all pairs — what the paper's "factor contribution" exhibit shows

If per-pair SHAP reveals systematic differences (bank pairs driven by vol features, equity-futures pairs driven by TSMOM), that's a research finding about pair heterogeneity.

### Ablation Analysis

Remove one feature group at a time from the full model:
- Full model → OOS Sharpe X
- Full minus regime → OOS Sharpe Y
- Full minus TSMOM → OOS Sharpe Z
- etc.

The degradation ΔSharpe = X - Y tells you the marginal value of each feature group. This is the paper's "factor contribution" section.

### Factor Comparison Matrix

Rows (12 factor combinations):
1. Z-score only (baseline — pure stat-arb signal)
2. Z-score + regime
3. Z-score + volume
4. Z-score + TSMOM
5. Z-score + Hurst filter
6. Z-score + realized skewness filter
7. Z-score + regime + volume
8. Z-score + regime + TSMOM
9. Z-score + all factors (full model)
10. Ablation: full minus regime
11. Ablation: full minus TSMOM
12. Ablation: full minus microstructure

Columns (12 metrics): IS Sharpe, OOS Sharpe, Sharpe decay ratio, Win rate, Profit factor, Max DD, Calmar, PBO score, # trades, Avg hold period, CVaR(95%), Sortino

= 144 cells; run overnight across all confirmed pairs

---

## backtest.py — Comprehensive Outline

### Purpose

Walk-forward backtesting of confirmed cointegrated pairs with multiple strategy variants, risk management approaches, and portfolio construction methods. Produces the performance statistics section of the paper and validates the ML signal's practical profitability.

### Strategy Variants

**Variant A — Standard long/short spread (baseline):**
Long leg A, short leg B when z-score > entry_threshold. Exit when z-score crosses exit_threshold. Outright equity/futures positions, no options.

**Variant B — Options overlay (spread view via options):**
Express the convergence view using options rather than shares. When spread is at +2σ (A rich, B cheap): buy puts on A + buy calls on B. This creates a position that profits from convergence without needing to borrow shares for shorting, and with defined maximum loss. Also tested alongside for comparison: outright shares + options hedge to examine when options add vs subtract value.

**Variant C — Delta-neutral with pairs-of-pairs:**
Portfolio of pair positions where the aggregate net beta to the S&P 500 ≈ 0. If pair 1 has net beta +0.2 and pair 2 has net beta −0.2, hold both. Removes systematic market risk while keeping idiosyncratic spread exposure. More complex to construct but produces the cleanest test of the cointegration signal.

All three tested for comparison. The paper reports which variant produces the best risk-adjusted OOS return and under which regime conditions each is preferable.

### Position Sizing

Four methods tested:

1. **Fixed 2% risk** — position sized such that the stop-loss represents 2% of account. Simple, well-understood, baseline.

2. **Half-Kelly** — Kelly fraction derived from win rate × payoff ratio, halved for estimation uncertainty. Requires 60+ trades before the Kelly estimate is reliable; documented as a bias in the early backtest period.

3. **Full-Kelly** — theoretical upper bound; reported for comparison but not recommended for live trading due to sensitivity to estimation error.

4. **Risk parity (all variants tested; significance determines final recommendation):**

   - *Independent risk parity*: each pair sized independently so its contribution to portfolio vol = target (e.g. 1% per pair). Simple, ignores cross-pair correlation. Equivalent to vol-scaling each position in isolation.
   - *True portfolio risk parity (cross-pair aware)*: optimize weights such that each pair contributes equally to total portfolio variance, accounting for realized cross-pair correlations. Requires solving a convex optimization (scipy.optimize or cvxpy). When bank pairs FITB↔TFC, KEY↔TFC, KEY↔PNC are all active simultaneously, their high mutual correlation means they each get smaller allocation than if uncorrelated — the correct risk-aware answer.
   - *Hierarchical risk parity (HRP)*: cluster pairs by correlation structure (hierarchical clustering on cross-pair correlation matrix), allocate within-cluster and between-cluster using inverse-variance. More robust than MV-based approaches because it avoids inverting a potentially ill-conditioned covariance matrix. A de Prado (2016) method.

   **Decision rule:** run all three alongside fixed 2% and half-Kelly. If no risk parity variant shows statistically significant OOS Sharpe improvement over equal-weight (permutation test p < 0.05), default to a smaller fixed allocation — simpler, more robust, and avoids the false precision of optimization on limited data. This outcome is also a publishable result: it suggests that for the confirmed pair set, correlation structure does not contain additional sizing information beyond the individual pair signals.

### Portfolio Construction

**Fragile-to-robust comparison spectrum (expanded 2026-06-21):** the original
three approaches below are retained; three more are added specifically to
build a fragile→robust comparison spectrum as a single paper exhibit, per
Michaud (1989)'s point that MV optimization "maximizes estimation error" —
the GAP between fragile and robust methods, not any one method's standalone
performance, is itself the paper finding.

1. **Tangency portfolio (max Sharpe / mean-variance optimal)** — maximizes
   w'μ/√(w'Σw) using the sample covariance and mean estimated in-sample.
   This **is** the mean-variance efficient frontier's optimal point — item 4
   below is the same object viewed as a curve rather than a single point.
   Included DELIBERATELY as the fragile baseline, not as a candidate for
   live use: the point is to quantify, not avoid, its estimation-error
   sensitivity against the actual confirmed pair universe.
2. **Minimum variance** — minimize w'Σw with no expected-return assumption
   at all. More robust to μ-estimation error than tangency since it drops
   one of the two noisy inputs.
3. **Minimum CVaR** — minimize portfolio CVaR(95%) directly, using the
   actual (likely fat-tailed, per the EVT/GPD fit in stats.py) shape of pair
   P&L rather than assuming variance captures tail risk. Natural comparison
   point against minimum variance once returns are confirmed non-normal.
4. **Mean-variance efficient frontier** — for each target return, minimize
   w'Σw; the (σ, μ) locus traces the frontier. Reports where equal-weight,
   risk parity, and HRP sit relative to it — the distance from the frontier
   IS the quantified "cost of not optimizing" (see Markowitz/efficient
   frontier section above).
5. **Maximum diversification** — minimize average pairwise correlation
   between positions. Naturally downweights clusters of similar pairs (e.g.
   the bank-pair cluster).
6. **Equal-weight baseline** — all confirmed pairs equally weighted. Reports
   whether any optimized method beats equal-weight OOS; often not the case
   (covariance estimation error), and reporting that failure honestly is
   itself rigorous.
7. **Independent / true portfolio / HRP risk parity** — see Position Sizing
   above; included again here as rows in the comparison table below rather
   than re-described.
8. **Constrained optimizer (added 2026-06-21)** — maximize a target metric
   (Sharpe, primarily; CVaR-adjusted Sharpe as a secondary objective) subject
   to: leverage ≤ L (gross exposure cap), turnover ≤ T per rebalance (an
   explicit cost penalty the OTHER seven methods don't have — they're
   re-solved each rebalance with no penalty for how far the new weights are
   from the old ones), and sector/concentration limits (e.g. via the HHI
   index already documented under Lopez de Prado above, or a hard per-sector
   exposure cap given the bank-pair cluster's concentration risk). This
   tests a DIFFERENT robustness axis than items 1-7: operational/
   implementation realism rather than covariance-estimation-error
   robustness. Compare against the unconstrained tangency/MV result
   specifically — the gap between unconstrained-optimal and
   constrained-optimal Sharpe is the "cost of realistic operating
   constraints," parallel to how the existing frontier distance is the
   "cost of not optimizing" (item 4 above). Implementation: standard convex
   optimization (`cvxpy` or `scipy.optimize` with linear/quadratic
   constraints) — turnover and gross-leverage limits are linear in the
   weight vector, so this stays a well-behaved QP/SOCP, not a harder
   combinatorial problem.

**Paper exhibit — Portfolio Construction Comparison Table (new):** one
table, rows ordered fragile → robust (tangency → minimum variance → minimum
CVaR → independent risk parity → true portfolio risk parity → HRP →
constrained optimizer), columns = OOS Sharpe, Max Drawdown, CVaR(95%),
computed on the confirmed pair universe. This is the exhibit that makes
"fragile vs. robust" a falsifiable empirical claim rather than an
assumption: if tangency's IS Sharpe is dramatically higher than its OOS
Sharpe while HRP/min-CVaR show a much smaller IS/OOS gap, that differential
decay — not any single Sharpe number — is the finding. If tangency instead
holds up OOS, that is a genuine, reportable surprise rather than something
to suppress. The constrained-optimizer row additionally quantifies how much
of any optimized method's apparent edge survives once leverage, turnover,
and concentration limits are imposed — a second, independent robustness
check alongside the IS/OOS gap.

### Risk Management Variants

Four exit triggers tested individually and in combination:
1. **Z-score stop** — exit if spread widens to N×entry_z (e.g. 3.5σ stop at 2.0σ entry)
2. **Portfolio drawdown stop** — close all positions if portfolio DD exceeds threshold
3. **Correlation exit** — exit if rolling 60-day correlation between legs drops below 0.20 (structural breakdown signal)
4. **Volatility scaling** — reduce position size proportionally when realized spread vol exceeds 1.5× long-run average; close if vol exceeds 3×

**Maximum holding period:** TBD after observing entry/exit behavior across pairs. The natural candidate is 3× half-life, but this will be calibrated empirically from the MAE/MFE distribution (what fraction of profitable trades peak before 3× half-life?). Documented as a methodology decision pending data.

### Strategy Greeks (Per Position, Reported in Risk Section)

- **Δ (delta):** net directional exposure at current hedge ratio
- **Γ (gamma):** rate of change of hedge ratio (how fast the hedge needs rebalancing)
- **ν (vega):** P&L sensitivity to a 1% change in spread volatility
- **θ (theta):** expected P&L time decay — related to half-life (fast-reverting pairs have high positive theta, slow pairs have low theta)
- **ρ (rho):** interest rate sensitivity — material for ZN/ZB pairs; small for equity pairs

### Performance Metrics

Full reporting table:
- Returns: total return, annualized return, daily/monthly P&L distribution
- Risk: VAR(95%), CVAR(95%), Max Drawdown, Average Drawdown, Drawdown Duration
- Risk-adjusted: Sharpe ratio, Deflated Sharpe (PSR), Calmar ratio, Sortino ratio
- Trade statistics: # trades, Win rate, Profit factor, Average trade P&L, Average holding period
- Execution: Slippage sensitivity (single assumption modeled), Commission impact
- Quality: MAE/MFE distributions, Bliss index (MFE/MAE ratio), Trade efficiency (final P&L / MFE)

### MAE/MFE Analysis

For every trade in the backtest:
- **MAE** (Maximum Adverse Excursion): worst point loss during holding period
- **MFE** (Maximum Favorable Excursion): best point gain during holding period

Uses: (1) calibrate stop placement — the MAE distribution tells you where stops should be to avoid premature exits while still protecting against genuine losses. (2) calibrate profit targets — MFE distribution shows how much profit is realistically achievable. (3) trade quality metric: efficiency = final P&L / MFE; bliss index = avg MFE / avg MAE.

### Entry/Exit Grid Heatmap

MC simulation across: entry z-scores {1.5, 2.0, 2.5, 3.0} × exit z-scores {0.0, 0.25, 0.5, 0.75} × stop z-scores {3.5, 4.0, 4.5} = 48 combinations. For each combination, 10,000 path simulations under the best-fit distribution. Report median OOS Sharpe as a color heatmap. The region where Sharpe is within 1σ of maximum is the stability region — a key parameter sensitivity exhibit.

### Combined vs Per-Pair Backtests

Both computed:
- **Combined backtest:** pool all pair trades together; report portfolio-level performance. Standard academic approach; most familiar to paper reviewers.
- **Per-pair backtest:** separate P&L for each pair; report each pair's individual Sharpe, DD, etc., then aggregate. More granular; shows which pairs drive performance and which are deadweight.

Report both; if combined and per-pair aggregate produce meaningfully different results, investigate why (likely driven by timing correlation between pairs).

### Parameter Stability and Sensitivity

**When to run:** after primary backtest results exist. Sensitivity is a robustness check, not a parameter selection tool.

**Tier 1 (analysis parameters):**
- Pearson threshold: 0.35–0.55 in 0.05 steps
- FDR alpha: 0.01, 0.05, 0.10, 0.15
- OU lookback window: 126, 252, 504 days
- BH correction level

**Tier 2 (signal parameters):**
- Entry z-score: 1.5, 2.0, 2.5, 3.0
- Exit z-score: 0.0, 0.25, 0.5, 0.75
- Stop z-score: 3.0, 3.5, 4.0, 4.5
- ML go-threshold: 0.50, 0.55, 0.60, 0.65

**Stability region:** the contiguous parameter space where OOS Sharpe stays within 1σ of the baseline. Wide stability region = robust; narrow = fragile/overfit. Visualized as a 2D heatmap per pair of parameters. This is a required section for any serious quant finance paper.

---

## stats.py — Comprehensive Outline

### Purpose

Statistical validation layer. Answers: are the strategy's returns statistically distinguishable from noise? What are the tail risk properties? How does performance hold under distributional assumptions other than normal?

### Confirmatory Cointegration Tests (KPSS + Phillips-Ouliaris)

Run after EG screening to produce Gold/Silver/Bronze tier assignments.

**KPSS (Kwiatkowski-Phillips-Schmidt-Shin):**
- Null hypothesis: series IS stationary (reverse of ADF)
- A pair where ADF rejects unit root AND KPSS fails to reject stationarity → strong bilateral evidence
- Conflict between ADF and KPSS → possible structural break; flag for StrategyDecayDetector

**Phillips-Ouliaris:**
- Tests null of NO cointegration
- Uses FM-OLS: corrects for serial correlation and endogeneity in finite samples
- More powerful than EG in small samples — critical for intraday pairs with 60–730 observations
- Two statistics: Z_α and Z_t (both reported)

**Tier assignments:**
- Gold: EG + KPSS + PO all confirm → primary paper findings
- Silver: two of three → included with notation
- Bronze: EG only → appendix with strong caveat

### Robust Hedge Ratio Comparison (Huber + MM)

For every confirmed pair, compute alongside existing OLS/TLS/Kalman:

**Huber regression:** hybrid squared/absolute loss at cutoff k=1.345σ. 95% Gaussian efficiency + outlier resistance. Correct choice when data has occasional large contaminations (earnings announcements, flash crashes).

**MM estimator:** 50% breakdown point via S-estimator initialization followed by M-estimator. Maximum robustness AND near-Gaussian efficiency. The gold standard for contaminated data.

**Comparison report:** for each pair, show OLS β, TLS β, Kalman mean β, Huber β, MM β. If all five agree within ±0.05, the hedge ratio is robust — high confidence. If they diverge, the relationship is sensitive to outliers — risk flag.

### EVT — Extreme Value Theory (Tail Risk)

For each confirmed pair's spread return distribution:
- Extract tail exceedances beyond the 95th percentile
- Fit Generalized Pareto Distribution (GPD) to exceedances
- Report shape parameter ξ: ξ > 0 = fat tails (Pareto), ξ ≈ 0 = exponential, ξ < 0 = bounded

Practical use: pairs with ξ > 0.3 have fat-tailed spread distributions. Their Kelly fractions need to be reduced and their stop losses need to be wider. The EVT ξ feeds directly into the backtest risk management logic.

### DCC-GARCH (Dynamic Conditional Correlation)

Model time-varying correlations between pair P&L streams:
- Fit DCC-GARCH(1,1) to the matrix of pair returns
- Extract time-varying correlation matrices
- Identify periods when pair P&L streams become highly correlated (regime of correlated losses)
- Report maximum drawdown under correlated loss regime vs uncorrelated regime

This is particularly relevant for bank pairs (FITB↔TFC, KEY↔TFC, KEY↔PNC) which will become highly correlated during financial stress — exactly when you want maximum diversification.

### Monte Carlo Simulation

**Phase 1 — Distribution fitting (both per-pair and best global):**

Per pair: fit each distribution family; report AIC/BIC; flag best-fit. The paper characterizes each pair's return distribution individually.

Global: identify the single distribution family that fits best across the majority of pairs — this becomes the primary simulation distribution.

Families tested:
1. Normal (baseline)
2. Student-t (estimate df via MLE)
3. NIG (Normal Inverse Gaussian — captures skewness + kurtosis)
4. Stable distribution (heavy tails, possible skewness)
5. GARCH(1,1)-filtered residuals (captures vol clustering)

**Phase 2 — Regime-conditional simulation:**

Bootstrap separately from each HMM regime (mean-reverting, trending, high-vol). Simulate long paths where regime transitions follow the estimated HMM transition matrix. More realistic than IID bootstrap because it preserves the clustering structure of market regimes.

Block size: tested at (1) mean HMM dwell time (natural choice — each block is one complete regime episode) and (2) fixed 20 bars. Both compared for sensitivity. If results differ materially, the block size matters and should be reported. If not, use mean dwell time as primary (more principled).

**Phase 3 — Slippage sensitivity:**

Single slippage assumption modeled (not per-share vs percentage): a unified bps-per-trade assumption. Tested at {0, 2, 5, 10, 20} bps per side. Report OOS Sharpe vs slippage curve per pair. The slippage breakeven (where Sharpe = 0) is the maximum market impact the strategy can sustain — critical for real-world implementability.

**Phase 4 — Trade quality:**

10,000 simulated path outcomes per entry signal. For each simulation:
- Record MAE, MFE, final P&L
- Compute efficiency = final P&L / MFE
- Compute bliss index = mean MFE / mean MAE
- Compare simulated MAE/MFE distributions to realized (backtest vs simulation calibration check)

**Phase 5 — Entry/exit grid heatmap (see backtest.py section)**

### Permutation Test / White Reality Check

**Portfolio-level test** (most conservative and most defensible):
- Compute realized portfolio Sharpe ratio S*
- Generate 1,000 permuted portfolios by shuffling the entry signal timestamps (signal dates randomized, trade P&L preserved)
- p-value = fraction of permuted Sharpe > S*
- If p < 0.05, portfolio performance is statistically significant under the null hypothesis of no predictable signal

The portfolio-level test is the right choice for the paper because:
1. It directly addresses "is the portfolio strategy better than chance"
2. It's more conservative than per-pair tests (lower power to over-claim significance)
3. It avoids the per-pair multiple testing burden

### Parameter Stability (Also in backtest.py)

After primary results exist, run sensitivity analysis across all Tier 1 and Tier 2 parameters (see backtest.py section). Report:
- Which parameters have stable OOS Sharpe across their test range (robust)
- Which parameters show a sharp optimum (fragile/overfit signal)
- The joint stability region visualization (2D heatmap per parameter pair)

---

## options.py — Comprehensive Outline

### Purpose

Options overlay for expressing spread views and hedging. Prices options on pair legs using institutional-grade models calibrated to observed implied volatility surfaces from CBOEFeed.

### Heston Model

The industry standard for equity options pricing with realistic implied volatility smile:

```
dS_t = r S_t dt + √v_t S_t dW^S_t
dv_t = κ(θ - v_t) dt + ξ√v_t dW^v_t
corr(dW^S, dW^v) = ρ
```

Parameters: κ (mean reversion speed), θ (long-run variance), ξ (vol of vol), ρ (return-vol correlation), v₀ (initial variance).

Calibration: minimize squared error between model-implied and market-implied vol surfaces from CBOEFeed data, using characteristic function pricing for speed. The Feller condition 2κθ > ξ² ensures variance stays positive.

Report per pair leg: calibrated Heston parameters, implied vol smile comparison to market, model fit quality (RMSE on IV surface).

### CRR Binomial Tree

American options pricing for equity options (which allow early exercise). Black-Scholes cannot price American options correctly. The Cox-Ross-Rubinstein binomial tree discretizes the underlying and computes option prices by backward induction, correctly handling early exercise at each node.

Use: protective puts on spread positions, calls on the cheap leg for delta-neutral entry.

### Monte Carlo Options Pricing

Path-dependent payoffs that closed-form models can't handle:
- Barrier options (knock-out at spread convergence — automatically exits when spread narrows)
- Asian options (average-price payoff — natural hedge for a pairs trade held over time)
- Spread options (payoff based on the spread itself rather than individual legs)

### Strategy: Spread View via Options

Rather than outright shares, express the convergence view via options:
- When z-score > 2.0 (A rich, B cheap): buy puts on A + buy calls on B
- Maximum loss: defined (total premium paid)
- Maximum gain: unlimited (if A falls and B rises to fully converge)
- No borrowing required for short side (puts replace short stock)

Tested alongside outright shares to determine:
- Under which conditions options outperform (high-vol environments where defined-risk matters)
- Under which conditions options underperform (low-vol environments where premium cost exceeds upside)
- What the implied breakeven convergence is for each options structure vs the OU model's expected convergence

### Greeks (Options Positions)

For any options position in the overlay:
- **Δ (delta):** net underlying exposure; target ~0 for delta-neutral entry
- **Γ (gamma):** convexity — positive gamma means position becomes more profitable as moves accelerate
- **ν (vega):** sensitivity to IV; positive vega benefits from IV expansion
- **θ (theta):** time decay cost per day of holding the options hedge
- **ρ (rho):** interest rate sensitivity — small for short-dated equity options
- **Vanna:** cross-sensitivity of delta to IV — important when both price and vol move
- **Volga:** convexity of vega — how much vega changes as IV changes

### Radon-Nikodym and Change of Measure

All options pricing operates under the risk-neutral measure Q. Performance backtesting operates under the physical measure P. The Radon-Nikodym derivative dQ/dP (stochastic discount factor) connects these. When reporting options-adjusted returns in the paper, the distinction between P-measure expected returns and Q-measure (risk-neutral) prices is explicitly maintained. This is a mark of rigorous methodology that reviewers at Columbia/Berkeley will look for.

---

## report.py — Comprehensive Outline

### Format: LaTeX

LaTeX is the universal standard for quantitative finance research papers. JFE, RFS, SSRN preprints, and every MFE program research project uses LaTeX. It produces precisely typeset mathematics, professional tables with statistical significance markers, and publication-quality figures embedded from matplotlib/pgfplots.

**Setup for Windows:** Install MiKTeX (free, Windows) and VS Code with LaTeX Workshop extension. The workflow: `report.py` generates `.tex` source files, VS Code compiles with `pdflatex`, produces a PDF indistinguishable from a published journal article.

All report output is fully reproducible from `output/results/` parquet and JSON files alone. Running `report.py` with no dependencies on live pipeline state regenerates the complete paper from saved outputs.

### Paper Structure (Academic Style)

```
Title, Author, Affiliation, Date, JEL Codes

Abstract (150–250 words)
  - Thesis statement
  - Methodology summary (3 sentences)
  - Key results (2 sentences)
  - Significance

1. Introduction
   1.1 Research Question and Thesis
   1.2 Contribution to Literature
   1.3 Related Work (cointegration pairs trading, regime detection, ML in finance)
   1.4 Paper Organization

2. Data and Universe Construction
   2.1 Asset Universe (529 assets, 6 classes, 12 TFs)
   2.2 Data Sources and Pipeline
   2.3 Bar Construction and Alignment (including 7D W-FRI derivation; 4h/8h documented limitations)
   2.4 Quality Control and Exclusions

3. Methodology
   3.1 Pre-Filter: Three Parallel Correlation Methods (Pearson/Spearman/rolling avg/dCor)
   3.2 Cointegration Testing (EG primary; KPSS + PO confirmatory; Gold/Silver/Bronze tiers)
   3.3 Hedge Ratio Estimation (OLS/TLS/Kalman/Huber/MM comparison)
   3.4 Spread Modeling (OU process, half-life, z-score)
   3.5 Regime Classification (K-means/GMM/HMM; auto-K; volatility-standardized features)
   3.6 Structural Pair Exclusions and Bias Taxonomy
   3.7 Machine Learning Signal (feature construction; multiclass classifier; WFA)
   3.8 Portfolio Construction (sizing; risk management; Greeks)
   3.9 Options Overlay (Heston; CRR; spread view via options)
   3.10 Parameter Sensitivity and Stability Region

4. Bias Audit
   4.1 Data Biases (survivorship, non-stationarity, alignment)
   4.2 Model Biases (lookahead, regime labeling, hedge ratio)
   4.3 Statistical Biases (multiple testing, evaluation methodology)
   4.4 Execution Biases (slippage, capacity, timing)
   Full tabular bias audit (mechanism / remedy / residual risk for each)

5. Empirical Findings
   5.1 Cointegration Discovery by Timeframe
   5.2 Confidence Tier Distribution (Gold/Silver/Bronze)
   5.3 Cross-Asset Pairs Analysis (15m ES↔utility sector finding)
   5.4 Trio Structures and Multivariate Cointegration
   5.5 Regime-Dependent Cointegration Stability
   5.6 Structural Pair Exclusions (forex triangles; share classes)
   5.7 Calibration Curves (Pearson threshold vs confirmation rate)
   5.8 Half-Life and Mean Reversion Speed Distributions

6. Machine Learning Results
   6.1 Feature Importance (SHAP: per-pair and aggregated)
   6.2 Factor Contribution Matrix (12 combinations × 12 metrics)
   6.3 Class Probability Calibration
   6.4 Model Comparison (XGBoost vs RF vs MLP)
   6.5 Ablation Analysis

7. Strategy Performance
   7.1 Walk-Forward Backtest Results (all variants)
   7.2 Risk-Adjusted Performance by Pair and Portfolio
   7.3 Strategy Greeks Analysis
   7.4 Options Overlay Comparison
   7.5 Slippage and Cost Sensitivity
   7.6 MAE/MFE Trade Quality Analysis

8. Parameter Sensitivity and Stability
   8.1 Tier 1 Parameters (analysis layer)
   8.2 Tier 2 Parameters (signal layer)
   8.3 Stability Region Heatmaps
   8.4 Overfitting Validation (WFA decay, PBO, PSR, Monte Carlo null)

9. Statistical Validation
   9.1 Confirmatory Cointegration (KPSS + PO tiers)
   9.2 Tail Risk (EVT/GPD shape parameters per pair)
   9.3 Dynamic Correlation (DCC-GARCH)
   9.4 Monte Carlo Distribution Analysis
   9.5 Permutation Test / Reality Check (portfolio level)

10. Strategy Decay Analysis
    10.1 Half-Life Trend (positive slope = decaying)
    10.2 Structural Break Detection (Zivot-Andrews, CUSUM)
    10.3 Rolling Cointegration Fraction
    10.4 Regime-Conditioned Decay

11. Conclusion
    11.1 Summary of Findings
    11.2 Thesis Validation
    11.3 Limitations
    11.4 Future Research Directions (synthetic bars; tick data; CRSP survivorship correction; real-time signal generation)

References

Appendices
  A. Full pair results tables
  B. Bias audit log (complete)
  C. Model parameter tables (Heston calibration per pair)
  D. Bronze-tier pairs (EG only, not used in primary strategy)
```

### Key Exhibits

All generated programmatically from `output/results/` files:

| Exhibit | Type | Description |
|---------|------|-------------|
| Fig 1 | Table | Universe composition by asset class and timeframe |
| Fig 2 | Heatmap | Confirmed pairs count by TF × confidence tier |
| Fig 3 | Line chart | Pearson calibration curve (threshold vs confirmation rate) |
| Fig 4 | Time series | Spread z-score with entry/exit markers for each Gold pair |
| Fig 5 | Bar chart | SHAP feature importance (aggregated across pairs) |
| Fig 6 | Matrix (144 cells) | Factor contribution matrix |
| Fig 7 | Table | Full performance metrics by strategy variant |
| Fig 8 | Heatmap | Entry/exit z-score grid (Sharpe by parameter) |
| Fig 9 | Heatmap | Parameter stability region (Tier 2 sensitivity) |
| Fig 10 | Distribution | MAE/MFE distributions with optimal stop/target overlaid |
| Fig 11 | Table | EVT tail risk (ξ parameter per pair) |
| Fig 12 | Time series | DCC-GARCH rolling correlation between pairs |
| Fig 13 | Chart | Monte Carlo P&L distribution vs realized |
| Fig 14 | Table | Bias audit taxonomy (full) |
| Fig 15 | Chart | Strategy decay: rolling Zivot-Andrews breaks |

### LaTeX Technical Notes

- Tables use `booktabs` package (professional ruled lines, no vertical rules)
- Statistical significance: * p<0.10, ** p<0.05, *** p<0.01 in parentheses below estimates
- Figures generated as high-DPI PNG from matplotlib and embedded via `\includegraphics`
- Mathematical notation follows standard econometrics conventions
- JEL codes: C22 (Time-Series Models), C53 (Forecasting Models), G11 (Portfolio Choice), G12 (Asset Pricing)
- Citations: BibTeX with natbib, author-year format (JFE style)

---

## Session Log

### Session 1 (2026-06-13)
- Initial architecture design; `data.py` v1; BUG-D01, BUG-D02 fixed; first successful universe build: 529 assets, 6,233 symbol-TF combinations

### Session 2 (2026-06-14, morning)
- `analysis.py` written (3,051 lines); BUG-A01 (core bug — 98% universe invisible); Pearson threshold lowered to 0.40; forex triangular exclusion; share-class exclusion; HMM warnings suppressed; script-hash invalidation; exclusion list persistence; incremental daily cache refresh; Spearman + rolling avg + dCor pre-filters implemented

### Session 3 (2026-06-14, afternoon/evening)
- Post-build freshness refresh for completed assets (BUG-D13); exclusion set propagated through UniverseResult to analysis.py (BUG-D14); 7D/1M moved from yfinance direct fetch to 1D resample (BUG-D11); period kwarg added to get_equity_history (BUG-D12); full bar alignment audit across all 12 TFs; comprehensive DEVELOPMENT.md written with all planned module outlines

### Next Session
- Implement Hurst exponent on every spread series in analysis.py
- Implement realized skewness per pair
- Add Huber + MM hedge ratio estimators to HedgeRatioEstimator
- Add KPSS + Phillips-Ouliaris to CointScanner
- Begin eigenportfolio decomposition as variant pipeline
- Run analysis.py with all fixes applied
- Read confirmed pairs to validate results before starting ml.py

---

## Known Data Issues

| Ticker | Issue | Status |
|--------|-------|--------|
| VLTO | Veralto Corp — no data | Hardcoded exclusion |
| BNY | Ticker variant — try BK | Hardcoded exclusion |
| FDXF | No daily data | Hardcoded exclusion |
| AOS, ABT, ABBV | 1m unavailable | Expected |
| 1m/2m/3m pairs | NTRS/STT identical to 1M — likely daily data in 1m cache | Investigate |
| GOOGL/GOOG | Structural — fixed | BUG-A03 |
| FOXA/FOX | Structural — fixed | BUG-A03 |

---

## Dependencies

```
Python          >= 3.10
ib_insync                 # IBKR TWS API
yfinance                  # Market data
pandas / numpy            # Core data
statsmodels               # EG, Johansen, OLS
scikit-learn              # KMeans, GMM, silhouette
hmmlearn                  # HMM
scipy                     # SVD, stats
pyarrow                   # Parquet I/O
exchange_calendars        # NYSE calendar
xgboost / lightgbm        # ML (planned)
shap                      # SHAP feature importance (planned)
arch                      # GARCH, DCC-GARCH (planned)
MiKTeX / TeX Live         # LaTeX compilation (planned)
```

IBKR: TWS or Gateway at 127.0.0.1:4001 (live) or 4002 (paper). Client ID 1.

---

## Model Recommendations

| Task | Model | Reasoning |
|------|-------|-----------|
| Planning, debugging | claude-sonnet-4-6 | Fast, sufficient |
| Writing large files | claude-opus-4-7 | Better sustained output |
| Hard statistical reasoning | claude-opus-4-8 | Best mathematical correctness |

---

## Session 3 Additions — Extended Concepts and Decisions

### Timeframe Coverage — Full Audit

**yfinance available intervals:**
1m (7d max), 2m/5m/15m/30m/60m/90m/1h (60d max), 1h (730d max), 1d/5d/1wk/1mo/3mo (full history)

**IBKR barSizeSetting (exact strings required):**
Seconds: "1 secs", "5 secs", "10 secs", "15 secs", "30 secs"
Minutes: "1 min", "2 mins", "3 mins", "5 mins", "10 mins", "15 mins", "20 mins", "30 mins"
Hours: "1 hour", "2 hours", "3 hours", "4 hours", "8 hours"
Daily+: "1 day", "1 week", "1 month", "1 year"
useRTH=1 restricts to regular trading hours; useRTH=0 includes pre/post-market.

**Current gaps worth considering:**
- 90m (yfinance): sits between 1h and 4h; could fill the gap in intraday coverage
- 10m, 20m (IBKR): more granular intraday; 10m in particular has ~4× the bars of 30m
- 3h, 2h (IBKR): between 1h and 4h with more bars per session
- 3mo (yfinance): quarterly — useful for very long-horizon studies

**Decision on additional TFs:** defer to later session. Current 12 TFs cover the essential spectrum. Additional TFs would increase runtime significantly and need a separate diagnostic run.

**IBKR 1m for equities — root cause of failures:**
IBKR paper accounts have stricter pacing for equity 1m data than live accounts. The current pipeline routes equities through yfinance for 1m (IBKR is used for non-equity assets). Q and SNDK fail at 1m from yfinance likely because: Q = Qualcomm (may have ticker conflict with historical Qwest), SNDK = SanDisk (acquired by WDC 2016 — ticker defunct). These are expected failures for retired/ambiguous tickers.

**IBKR durationStr guardrail:**
For very fine bar sizes, IBKR rejects requests for excessive history. Max lookback by bar size:
- 1 min: max 1 month (we use 1D duration → 1 day of 1m data per request)
- 5 min: max 6 months
- 1 hour: max 1 year
Our current pipeline respects these by limiting intraday requests to appropriate durations.

### Dollar Bars (Lopez de Prado)

Traditional time bars have non-constant variance — a 15-minute period at market open (high activity) and a 15-minute period at mid-day (low activity) contain very different amounts of information. This violates the IID assumption that many statistical tests require.

**Dollar bars:** sample one bar for every $X of notional traded. Each bar represents equal economic activity regardless of calendar time. Properties:
- More statistically homogeneous variance across bars
- Better IID properties for ML features
- Natural handling of volatility clustering (volatile periods → more bars; quiet periods → fewer bars)
- Addresses autocorrelation in variance that GARCH tries to model

**Volume bars:** same idea, sampled every N shares/contracts traded.
**Tick bars:** sampled every N transactions.
**Range bars:** sampled when price moves ±X from bar open.

**Applicability to CAMARF:** requires tick or transaction-level data, which we don't currently collect. Our 1m OHLCV is the finest granularity available from IBKR/yfinance. Dollar bar construction from 1m bars is possible (approximate) by distributing volume proportionally. This is noted as a significant future extension for CAMARF v2 — it would meaningfully improve the statistical properties of intraday features.

**Research reference:** Lopez de Prado (2018), "Advances in Financial Machine Learning", Chapter 2.

### Sharpe Ratio as Function of Independent Bets (Grinold & Kahn)

This is one of the most important concepts for reporting strategy performance honestly.

**Fundamental Law of Active Management (Grinold & Kahn 1992):**
IR = IC × √BR

Where:
- IR = Information Ratio (risk-adjusted alpha)
- IC = Information Coefficient (correlation between forecasts and outcomes)
- BR = Breadth (number of INDEPENDENT bets per year)

**The Sharpe ratio is NOT a fixed number for a strategy.** It depends on:
1. **Observation frequency:** Sharpe scales as √T for uncorrelated returns, where T = number of periods. Annualizing: SR_annual = SR_per-period × √(periods/year). A strategy with daily Sharpe 0.05 has annual Sharpe ≈ 0.05 × √252 ≈ 0.79.
2. **Effective BR vs gross trade count:** If 10 trades are all in the same sector during the same event, they have effective BR ≈ 1, not 10. The Sharpe from correlated bets does NOT scale as √10 — it barely moves.
3. **Autocorrelation in returns:** If returns are positively autocorrelated (momentum), the Sharpe formula must use the autocorrelation-adjusted standard deviation: SR_adj = mean_ret / std_ret × √((1+ρ)/(1-ρ)) for lag-1 autocorrelation ρ.

**For CAMARF specifically:**
- Count independent bets as the number of DISTINCT confirmed pair entries that share no common leg and occur during different market regimes
- Three bank pairs (FITB↔TFC, KEY↔TFC, KEY↔PNC) entered simultaneously = effective BR ≈ 1 (highly correlated), not 3
- ES↔utility pair and NTRS↔STT entered simultaneously = effective BR ≈ 2 (different sectors, different dynamics)
- The True BR feeds directly into the Kelly fraction: Kelly = SR / var_of_bets × BR_effective

**Implementation:** report two Sharpe figures in backtest.py:
1. Naive Sharpe: total P&L / total std, annualized by √T
2. BR-adjusted Sharpe: accounts for correlation between pair trades, gives more honest assessment of strategy diversification

### Crypto Missing Bars — Correct Treatment

Crypto trades 24/7; traditional markets have session gaps. Treating them identically is wrong.

**Rule:**
- 1-bar gap (1 missing bar): flag as `no_activity` — genuine absence of trades. Price unchanged, volume = 0. Use forward fill for price but flag with `is_no_activity=True`. Does NOT affect correlation (zero return for that period in both assets is a real observation: nothing happened).
- Multi-bar gaps in crypto: flag as `is_gap=True` with a subtype. For gaps of 2-4 bars: likely data issue. For gaps of 5+ bars: potentially exchange downtime or delisting.
- Equity-vs-crypto alignment on intraday: equity overnight = expected session gap (8h+ of no trading). Crypto during equity overnight = active trading period. When computing cross-asset correlations, only the equity session hours (9:30–4:00 ET) should be used, since equity prices don't move during those crypto-active overnight periods. The cross-asset correlation at 15m uses only bars where BOTH assets have active data.

**Implementation in DataAligner:** add `is_no_activity` flag for single-bar crypto gaps (volume = 0 and price unchanged from previous bar). Exclude `is_no_activity` bars from correlation computation without forward-filling, since a 0-volume bar contributes artificially to mean calculations.

### Volatility Adjustment for VolumeStructure Features

ALL 12 VolumeStructure features must be dimensionless and volatility-standardized before entering the ML model. Current status and required adjustments:

| Feature | Current | Required adjustment |
|---------|---------|---------------------|
| relative_volume | vol/rolling_avg | ✅ Already normalized |
| dollar_volume | raw dollars | ÷ rolling_std(dollar_volume, 252) |
| vwap_deviation | (close-vwap)/vwap | → should be (close-vwap)/σ_close to be in σ units |
| amihud_illiquidity | return/volume ratio | ÷ rolling_std(amihud, 252) to make cross-asset comparable |
| cvd_proxy | signed volume | ÷ rolling_std(volume, 20) |
| large_move_low_vol | binary flag | ✅ Already binary |
| high_vol_small_move | binary flag | ✅ Already binary |
| volume_divergence | difference | ÷ rolling_std(volume_divergence, 252) |
| squeeze_indicator | BB/KC ratio | ✅ Already a ratio, bounded approximately |
| rsi_14 | [0, 100] bounded | (RSI - 50) / 25 to center on zero and scale to ±2 σ-like range |
| relative_vol_ratio | ratio | ✅ Already normalized (current vol / long-run vol) |
| cross_leg_rsi_divergence | RSI_A - RSI_B | ÷ 50 to normalize to [-2, 2] range |

**Implement in VolumeStructure.compute_features() before next run.** The ML model should never see raw dollar amounts or raw volumes — only their relative, volatility-normalized versions. This is the same principle as using returns instead of prices.

### Research Context Framing

**Updated framing:** CAMARF is an independent quantitative research project in statistical arbitrage and cross-asset co-movement. It is being developed to contribute original empirical findings to the academic and practitioner literature. The research also serves as a primary portfolio piece during a planned academic transition into quantitative finance graduate programs (MFE/FE).

The paper should stand on its own methodological merits. The committee audience context is noted in DEVELOPMENT.md for awareness but should NOT appear in the paper itself — the paper is pure research, written at the standard of a peer-reviewed finance journal.

### Reference Authors — Concepts and Applicability

**Marcos Lopez de Prado ("Advances in Financial Machine Learning", 2018; "Machine Learning for Asset Managers", 2020)**

Most directly applicable book for this project. Key concepts:

- *Dollar/Volume/Tick bars*: statistically superior to time bars; planned for CAMARF v2
- *Triple-barrier method*: labeling scheme for ML classification — define profit target, stop loss, and time limit; the first barrier hit determines the label. More principled than our current fixed-horizon labeling. Should evaluate as alternative label construction.
- *Purged k-fold cross-validation*: removes training samples that are within an embargo period of each test fold, preventing leakage from overlapping labels. Replaces standard k-fold which is invalid for time-series.
- *Combinatorial purged cross-validation (CPCV)*: generates many train/test path combinations for a distribution of Sharpe ratios rather than a single estimate. The variance of the Sharpe distribution is itself a measure of model robustness. IMPLEMENT in backtest.py.
- *Meta-labeling*: a two-stage classifier where Stage 1 produces a signal (our cointegration z-score) and Stage 2 (meta-labeler) predicts whether Stage 1 is correct. The meta-labeler learns when the primary signal is reliable. This is EXACTLY what our ML layer is doing — CAMARF's ML is a meta-labeler on the cointegration signal.
- *Feature importance via MDI/MDA/SFI*: Mean Decrease Impurity, Mean Decrease Accuracy, Single Feature Importance. More robust than vanilla SHAP for financial data. Report all three in the paper.
- *PBO (Probability of Backtest Overfitting)*: derived from CPCV; essential for the overfitting validation chapter.
- *HHI (Herfindahl-Hirschman Index) for concentration*: measure concentration of bets across pairs, sectors, time. A portfolio of bank pairs has high HHI = low diversification.
- *Bet sizing via Kelly*: the connection between IC, IR, and optimal bet sizing is formalized here.

**Antti Ilmanen ("Expected Returns", 2011)**

Essential for understanding economic mechanisms behind factor premia. Key concepts:

- *Risk premia framework*: returns come from bearing risk, not from information. Understanding which risks we're bearing in CAMARF pairs (liquidity risk? earnings event risk? macro sensitivity?) is essential for the paper's economic interpretation section.
- *Carry, momentum, value as pervasive factors*: cross-asset, cross-timeframe. The ES↔utility pair may be a carry relationship (utilities are bond proxies; ES captures risk appetite). Document the economic mechanism.
- *Trend-following vs mean-reversion*: Ilmanen shows mean reversion is strongest at short horizons (minutes to days) and long horizons (years); momentum dominates at medium horizons (1-12 months). Our finding that mean reversion is strongest at 1h and 1D is consistent with this.
- *Diversification*: the only free lunch; quantified by correlation decay. Pairs in different sectors provide genuine diversification; same-sector pairs (bank cluster) do not.

**Grinold & Kahn ("Active Portfolio Management", 2000)**

The mathematical foundation of systematic portfolio management.

- *Fundamental Law of Active Management*: IR = IC × √BR (see above — critical for honest Sharpe reporting)
- *The transfer coefficient*: fraction of IR actually captured after portfolio constraints (long-only constraint, position limits, transaction costs). For pairs trading, the transfer coefficient is high because we have fewer constraints.
- *Alpha model vs risk model*: the alpha model generates forecasts (our cointegration z-score + ML signal); the risk model measures covariance between bets (DCC-GARCH). Optimal portfolio combines both.
- *Backtesting framework*: alpha decay (IC decreasing as we look further ahead), which we measure via the Hurst half-life trend.

**Chincarini & Kim ("Quantitative Equity Portfolio Management", 2006)**

Factor models and statistical arbitrage.

- *Factor model decomposition*: R = Bλ + ε where B is factor loadings, λ is factor returns, ε is idiosyncratic. Cointegration on the ε component (idiosyncratic returns after factor removal) is the CORRECT approach — this is eigenportfolio decomposition using Marchenko-Pastur.
- *Cointegration in multi-factor models*: pairs that are cointegrated in raw returns may be spuriously so due to shared factor exposure. Removing systematic factors first (eigenportfolio) finds genuine idiosyncratic relationships.
- *Risk decomposition*: total risk = systematic risk + idiosyncratic risk. Pairs trading profits from idiosyncratic risk; systematic risk should be hedged away.

**Shreve ("Stochastic Calculus for Finance I & II", 2004)**

The mathematical backbone for options.py and understanding measure theory.

- *Ito's lemma*: the chain rule for stochastic calculus; essential for deriving the BS and Heston PDEs
- *Girsanov's theorem*: the practical implementation of Radon-Nikodym for Brownian motion; changes the drift of a Brownian motion by changing measure. This is how we go from P-measure (real world) to Q-measure (risk-neutral) in options pricing.
- *Feynman-Kac theorem*: the connection between PDEs and expectations under Q; converts the options pricing PDE to an expectation problem that Monte Carlo can solve.
- *Martingale representation theorem*: any martingale under Q can be written as a stochastic integral — the theoretical foundation for delta hedging.

Learning priority: Chapters 1-4 of Volume I are accessible and sufficient for understanding the measure-theoretic foundations underlying options.py.

**Hull ("Options, Futures, and Other Derivatives", 2022, 11th edition)**

The standard industry reference. Less mathematically demanding than Shreve.

- *Greeks derivations*: exact formulas for Δ, Γ, ν, θ, ρ in Black-Scholes context; also for futures
- *Black-Scholes assumptions and violations*: constant vol (violated), log-normal distribution (violated in tails), continuous hedging (violated in practice). Knowing what's violated tells you when Heston is needed.
- *Futures and forward pricing*: cost-of-carry model; essential for understanding ES futures pricing relative to the cash SPX index
- *Interest rate derivatives*: relevant for ZN/ZB pairs in our universe
- Chapters 17-20 on exotic options are directly applicable to options.py

**McDonnell ("Algorithmic Trading and DMA", 2010)**

Execution-focused. Key concepts for implementation:

- *Market microstructure*: how orders move through the book; why the true slippage depends on order size relative to market depth
- *VWAP/TWAP execution algorithms*: standard benchmarks for institutional execution; relevant for understanding what "slippage" means in our backtest
- *DMA (Direct Market Access)*: the mechanics of how algorithmic orders reach the exchange; relevant for understanding IBKR's paper trading environment
- *Transaction costs modeling*: the square-root market impact model (cost ∝ √(size/ADV)); more realistic than fixed-bps assumption for larger positions

### Portfolio Theory — Markowitz and Efficient Frontier

**Mean-Variance Optimization (Markowitz 1952)**

Given N assets with expected returns μ (N×1) and covariance matrix Σ (N×N):

Minimize:  w'Σw  (portfolio variance)
Subject to: w'μ = target_return, Σw_i = 1, (optionally) w_i ≥ 0

The solution traces out the efficient frontier — the set of portfolios with maximum expected return for each level of variance (or equivalently, minimum variance for each level of expected return).

**For CAMARF pairs portfolio:**
- N = number of confirmed pairs (6-29 across timeframes)
- μ = expected P&L per pair (estimated from IS data — lookahead-biased; use OOS rolling estimate)
- Σ = covariance matrix of pair P&L streams (estimated from DCC-GARCH)
- The Σ matrix has high off-diagonal elements for same-sector pairs (bank cluster, etc.)
- Optimal weights concentrate in low-correlation pairs (the cross-asset 15m pairs may dominate the optimal portfolio despite lower individual Sharpe)

**Practical limitations of MV optimization:**
1. Σ estimation error causes instability — small estimation errors in Σ flip optimal weights dramatically (Michaud, 1989: "optimization maximizes estimation error")
2. Ill-conditioned Σ when N > T (more pairs than observations) — use shrinkage (Ledoit-Wolf) or factor-based Σ
3. Concentrated solutions — optimal weights often put everything in 1-2 pairs; constrain with w_max ≤ 0.30

**Alternatives implemented in backtest.py:**
1. Maximum Sharpe portfolio: maximize w'μ / √(w'Σw) — finds the portfolio on the efficient frontier with best risk-return tradeoff
2. Minimum variance: minimize w'Σw regardless of expected return — most robust to μ estimation error
3. Maximum diversification: maximize w'σ / √(w'Σw) where σ is vector of individual pair vols
4. Risk parity variants (see earlier section)
5. Equal weight (baseline)

**The efficient frontier as a research exhibit:** plot the frontier of pair portfolios in (volatility, expected return) space. Mark where equal-weight, risk parity, and max-Sharpe portfolios sit on the frontier. Show how far from the frontier equal-weight is — this quantifies the "cost of not optimizing."

**Black-Litterman model (extension):** combines investor views with market equilibrium returns via Bayes theorem. Our ML signal provides the "views" (P(strong_converge) > 0.70 → bullish view on spread convergence). The posterior expected returns blend the ML signal with a prior. Worth exploring as an advanced portfolio construction layer in a future session.

### Additional Strategy Concepts to Implement

**Straddles and Strangles as spread expression (confirmed as strategy variant):**
When the ML model has high entropy (uncertain between converge and diverge), a volatility trade (straddle/strangle) rather than a directional trade may be appropriate. The implied volatility of the options embeds a view on future spread volatility. If our OU model predicts lower spread vol than the IV implies, we can sell volatility (sell straddle). If higher, buy volatility (buy straddle). This connects options.py directly to the spread model's vol estimates.

**Regime-dependent risk sizing:**
In a mean-reverting regime (HMM state 1): full position size per Kelly
In a trending regime (HMM state 2): reduce to 25-50% of Kelly (mean-reversion strategy in wrong regime)
In a high-vol regime (HMM state 3): reduce to 10-25% of Kelly or skip entirely
The regime probabilities (soft labels from HMM) can scale position size continuously rather than discretely.

**Black swan events / tail risk management:**
EVT shape parameter ξ per pair determines the tail regime. Additional rule: if realized spread return exceeds 4σ in any single session, mandatory position review. If the 3-day spread return exceeds 6σ, exit at market open regardless of ML signal — this is the "black swan exit" that overrides all other logic. Size positions such that the worst historical 5-day drawdown per pair (from EVT simulation) is bounded at 3% of portfolio.

**Backtesting with cross-validation (combinatorial purged CV per Lopez de Prado):**
Rather than a single train/test split, CPCV generates C(T, k) combinations of k non-overlapping test periods from T total periods, with embargo periods between training and testing samples. This produces a DISTRIBUTION of Sharpe ratios across test paths, not a single point estimate. Report: median CPCV Sharpe, 5th percentile, and PBO score. A strategy with median Sharpe 1.4 and 5th percentile Sharpe 0.3 is far less reliable than one with median 1.0 and 5th percentile 0.8.

**WFO emulation test (walk-forward optimization treating bars as if newly received):**
Simulate real-time signal generation by processing bars one at a time in chronological order, maintaining only the feature state that would have been available at each bar timestamp. This is different from standard WFO (which refits the model on expanding windows) — the emulation test uses the SAME model fitted on IS data but applies it bar-by-bar in OOS, checking that no bar timestamp lookahead occurs. This is the gold standard for verifying that the backtest matches what would have happened in live trading.

### BUG-D15: Cache Deletion via rename on Windows/OneDrive

**Root cause:** `shutil.rmtree()` fails with WinError 5 (access denied) when OneDrive is actively syncing parquet files. The file handles are held by the OneDrive sync process.

**Fix:** Replace delete with atomic rename. `os.rename()` succeeds even when OneDrive holds file handles because it moves the directory entry at the filesystem level without touching individual file handles. Old result directories are renamed to `{tf_label}_stale_{timestamp}`. A cleanup pass removes old stale directories after the new run writes fresh results. If rename also fails (rare: network drive permission boundaries), the pipeline writes fresh files in-place — parquet files are overwritten by name, so stale data is naturally replaced.

### BUG-A07: Hurst Estimator Wrong Domain

**Root cause:** Both R/S and DFA were applied to spread LEVELS. For a stationary AR(1) spread with phi=0.90, the levels have strong POSITIVE autocorrelation (ρ_levels = phi = 0.90), so R/S on levels gives H > 0.9. For DFA on the cumsum of levels (double integration of a near-random-walk), the scaling exponent saturates at 1.0. Neither result is diagnostic for mean reversion.

**Fix:** 
- R/S applied to INCREMENTS (np.diff(spread)). Increments of OU have NEGATIVE lag-1 autocorrelation = (phi-1)/(2-phi) < 0 for all phi < 1, giving H < 0.5.
- DFA applied to the profile Y = cumsum(diff(spread) - mean(diff(spread))). For negatively autocorrelated increments, Y is anti-persistent → H_dfa < 0.5.

**Verified on 1000-bar simulations:**
- OU phi=0.70: H_rs=0.31, H_dfa=0.15 (strongly mean-reverting) ✓
- OU phi=0.90: H_rs=0.44, H_dfa=0.29 (mean-reverting) ✓
- OU phi=0.95: H_rs=0.53, H_dfa=0.42 (near random walk — reasonable for mild MR) ✓
- Random walk: H_rs=0.59, H_dfa=0.53 (above 0.5, correct) ✓
- Trending: H_rs=0.58, H_dfa=0.49 (above 0.5 for R/S, correct) ✓

**ML gate:** H_rs < 0.50. Pairs with near-random-walk spreads (phi≥0.95) correctly excluded from primary ML pipeline.


---

## Session 4 — Full Concept Compendium

### Research Philosophy

CAMARF is simultaneously a research project and a learning vehicle. Every methodological decision is evaluated against two standards: (1) is it academically defensible to a quantitative finance committee, and (2) does it deepen understanding of the underlying financial mechanisms? These two standards are usually aligned but where they diverge, academic rigor takes precedence.

The research operates under a bias-first design philosophy: every data choice, model selection, and statistical test is evaluated for the bias it introduces BEFORE implementation. No methodological "improvement" is shipped without documenting its bias footprint in the BiasAuditLog. An improvement that increases Sharpe but introduces unquantified lookahead is not an improvement.

### Asset Universe Selection Rationale (for paper)

**Positive framing for academic paper:**

The equity universe is restricted to S&P Composite 1500 constituents (S&P 500 + MidCap 400 + SmallCap 600). This selection is deliberate and methodologically motivated:

1. **Quality screening:** S&P index inclusion requires minimum market capitalization, demonstrated operational profitability, adequate public float (≥50% of outstanding shares publicly traded), and minimum liquidity thresholds. This eliminates speculative, distressed, and illiquid stocks where apparent cointegration would be data artifacts rather than genuine economic relationships.

2. **Economic significance:** S&P 1500 components represent the most economically meaningful publicly-traded businesses in the U.S. economy. Cointegration found within this universe reflects real business relationships — shared supply chains, common customer pools, correlated regulatory environments, competing for the same capital.

3. **Arbitrage rationale:** The strategy capitalizes on temporary divergences from equilibrium relationships between assets that share genuine economic cointegration. When economically related assets deviate from their historical co-movement — due to transient information asymmetry, order flow imbalance, or short-term sector rotation — the strategy provides liquidity by taking the convergence trade. The quality of the underlying businesses makes this convergence economically reliable rather than purely statistical.

4. **Data availability:** S&P 1500 components have complete, reliable price histories from multiple independent data sources (IBKR, yfinance, Bloomberg). Cross-validation between sources is possible; data errors are detectable.

**Framing to avoid:** "stocks likely to go up" — use "economically significant businesses with demonstrated operational viability" instead.

### Data Pipeline Philosophy

**Golden rule: never lose good data.** The pipeline uses three-tier data integrity checks:

1. **Freshness check** (`DataStore.is_fresh()`): is the cache file recent enough? Prevents unnecessary re-fetches.
2. **Frequency validation** (`DataStore.validate_frequency()`): does the cached data have the right bar spacing for its labeled TF? Catches the 1m/1M Windows collision bug.
3. **Sufficiency check** (`DataStore.is_data_sufficient()`): does the cached data have enough bars for the expected lookback? Catches truncated yfinance fallback data (1458 bars at 8h when IBKR provides 5861).

Only data that FAILS at least one of these checks gets re-fetched. Good data is never overwritten with equal or worse data. When IBKR provides deeper history than yfinance, the upgrade queue re-tries IBKR after the main sweep (when API congestion typically clears) to extend history.

**IBKR vs yfinance hierarchy:**
- Equities daily: yfinance (reliable, fast, full history)
- Equities intraday: IBKR first (deeper history), yfinance fallback (reliable, less history)
- ETFs: same as equities
- Crypto: yfinance (24/7, reliable)
- Forex: IBKR (primary), yfinance EURUSD=X format (fallback)
- Commodities: IBKR only (yfinance has no reliable commodity intraday)
- Futures: IBKR only

**IBKR failure root cause:** pacing limits. With 1000+ assets swept in sequence, IBKR's API rate limiter fills during burst windows. Assets that happen to request during a congested window fail (4 retries, 75s wasted) while nearby assets succeed. The fix is a rolling failure rate detector: when 70%+ of the last 10 attempts fail, switch to batch yfinance for all remaining assets in that TF (saves hours of retry waste). After the main sweep, IBKR upgrade pass retries for deeper history when congestion clears.

### Timeframe Expansion Rationale

**Current 14 TFs:** 1m, 2m, 3m, 5m, 15m, 30m, 1h, 4h, 8h, 1D, 7D, 1M, 3M, 6M

**New additions:**
- **3M (quarterly):** Natural business cycle frequency. yfinance `QS` resample from 1D. ~80 bars for 20-year history — adequate for EG. Captures multi-quarter cointegration driven by earnings cycles, capital allocation cycles, and seasonal business patterns. Expected to show fewer but more persistent confirmed pairs than monthly.
- **6M (semi-annual):** 2QS resample from 1D. ~40 bars for 20 years — borderline for EG reliability. Include with explicit caveat in paper: "semi-annual pairs reported as exploratory given limited sample size (N≈40)."

**Why not 1Y:** ~20 annual bars. EG requires minimum ~30 observations for meaningful inference. Not included.

**8h TF recharacterization:** As documented, NYSE trading session is 6.5 hours. IBKR's "8h" bar gives one bar per session (same as daily but labeled differently). In analysis, 8h results are expected to be nearly identical to 1D. This is noted in the paper as a methodology limitation.

### Stress Testing Framework (Planned — stats.py / backtest.py)

Stress testing answers: does the strategy survive realistic worst-case scenarios, or does it only work in calm markets?

**Category 1 — Historical stress events:**
Replay strategy through identified crisis periods with actual market data:
- 2008 GFC (Sep 2008 – Mar 2009): extreme correlation convergence, liquidity drought, leverage unwind
- 2020 COVID crash (Feb 19 – Mar 23, 2020): fastest -34% decline in S&P history, VIX>80
- 2022 rate hike shock (Jan – Oct 2022): simultaneous equity/bond selloff, TINA reversal
- Regional bank stress (Mar 2023): SVB collapse — directly relevant to FITB↔TFC, KEY↔TFC pairs

For each event: report maximum drawdown, drawdown duration, number of pairs that "broke" (cointegration fraction dropped below 0.50), and strategy P&L through the event.

**Category 2 — Synthetic stress scenarios:**
Monte Carlo paths conditioned on crisis distributions (EVT/GPD tail fitting):
- Correlation convergence stress: boost all pairwise correlations by +0.3 simultaneously (crisis contagion)
- Volatility spike: multiply spread volatility by 3× for 20 days (simulates VIX spike)
- Liquidity stress: widen bid-ask spreads 5× during stress period (execution cost shock)
- Regime shift: force all pairs into "trending" regime simultaneously (worst case for mean-reversion strategy)
- Leverage stress: test at 1×, 2×, 3× leverage; find the Kelly fraction that survives each scenario

**Category 3 — Strategy-specific stress:**
- Half-life decay stress: what if all confirmed pairs' half-lives doubled overnight? (structural change)
- Factor neutrality stress: correlation between pairs spikes to 0.95 (correlated bank pairs now perfectly correlated)
- Signal degradation: IC drops from actual level to 0.02 — where does the strategy break even?

**Key output:** strategy "stress map" — a matrix of (crisis scenario × severity level × Sharpe outcome). Pairs that survive all scenarios are the highest-conviction positions. Pairs that fail under mild stress are Silver tier regardless of raw Sharpe.

**Why stress testing matters for the paper:** any reviewer at a CFA/CAIA level will ask "what happens in 2008?" Having the answer explicitly — with numbers, not just "diversification helps" — is what separates academic research from naive backtesting. Lopez de Prado makes this point strongly: a strategy that hasn't been stress-tested hasn't been tested.

**Priority note (added 2026-06-21):** this section, plus the per-position
VaR(95%)/CVaR(95%) already listed under Performance Metrics, is core to
the thesis, not an optional add-on to consider later. A stat-arb paper
without explicit crisis-period survival evidence is incomplete, especially
given the confirmed bank-pair cluster (FITB↔FULT, PNC↔FULT) — Category 1's
"Regional bank stress (Mar 2023)" scenario is directly testing whether
THOSE specific confirmed pairs survive the exact kind of stress event their
own sector is most exposed to. When `backtest.py` gets built, this
portfolio-level VaR + historical-crash stress-test work should be
prioritized alongside the core performance metrics, not sequenced after
them as a nice-to-have.

### Cross-Validation Methodology (Combinatorial Purged CV)

Standard k-fold cross-validation is invalid for time series — training samples adjacent to test samples leak information. Lopez de Prado's CPCV addresses this.

**The problem in detail:** if NTRS↔STT converges over days 100-120 and the label for day 100 looks 26 days ahead to day 126, then any training sample from days 115-140 "knows" about the convergence that the model is trying to predict. This inflates in-sample performance metrics and causes overfitting.

**Purged k-fold:** for each train/test fold split, remove all training samples within [t - embargo, t + label_horizon] of any test sample. The embargo period = max(label_horizon, half_life) bars.

**CPCV:** extend purged k-fold to enumerate C(T, k) combinations of k test periods from T total periods. Each combination gives an OOS Sharpe estimate. The distribution of these estimates characterizes the model's true OOS performance. Key outputs:
- Median CPCV Sharpe (central estimate)
- 5th percentile Sharpe (downside estimate — what if we got unlucky?)
- PBO score (fraction of permuted test paths that beat the real path — should be < 0.50)

**Implementation:** CPCV for a 5-year daily dataset with 21-day label horizon and 10 test periods: C(10, 2) = 45 combinations → 45 OOS Sharpe estimates → robust distribution characterization. This is the primary validation framework in backtest.py.

### Markowitz / Efficient Frontier Theory (Full Reference)

**Setup:** N pair strategies with return vector μ (expected P&L, N×1) and covariance matrix Σ (pair P&L covariances, N×N). Portfolio weights w (N×1) summing to 1.

Portfolio expected return: E[Rₚ] = w'μ  
Portfolio variance: Var(Rₚ) = w'Σw

**Efficient frontier:** for each target return, minimize w'Σw. The (σₚ, μₚ) locus traces the frontier. Points below the frontier are dominated — you can get more return for the same risk.

**Maximum Sharpe portfolio (tangency):** maximize (w'μ - Rf) / √(w'Σw). This is the optimal risky portfolio; all investors should hold this combined with the risk-free asset in their preferred ratio.

**For CAMARF:** run MV optimization on pair P&L streams with Ledoit-Wolf shrinkage on Σ. Report: where does the equal-weight portfolio sit relative to the frontier? Where does risk parity sit? The gap between equal-weight and the frontier IS the opportunity cost of not optimizing — quantified, not assumed.

**Black-Litterman for ML signal integration:** the ML model's predicted convergence probabilities become "views" in the B-L framework:
- Prior: equilibrium returns implied by equal-weight portfolio (CAPM-style)
- Views: pairs with P(strong_converge) > 0.70 have expected return = prior + view_strength
- Posterior: weighted blend of prior and views → optimal portfolio
- This converts the ML probability output directly into portfolio weights

**Estimation error problem:** sample Σ from historical P&L is noisy. Michaud (1989) showed MV optimization "maximizes estimation error." Mitigations: Ledoit-Wolf shrinkage, Black-Litterman, robust optimization over uncertainty set.

### Grinold & Kahn — Full Framework

**Fundamental Law of Active Management:**
IR = IC × √BR_effective

Where:
- IR = Information Ratio (risk-adjusted alpha)
- IC = correlation between forecasts and outcomes (the edge per bet)
- BR = number of INDEPENDENT bets per year

**Autocorrelation-adjusted Sharpe (primary metric in backtest.py):**

Standard Sharpe: SR = μ / σ  
Adjusted Sharpe: SR_adj = SR × √((1 - ρ₁) / (1 + ρ₁))

where ρ₁ is lag-1 autocorrelation of strategy returns.

For mean-reverting pairs strategies: ρ₁ < 0 (returns alternate sign — win then flat, win then flat). This makes SR_adj > SR_naive. Reporting this is honest: the strategy is BETTER than naive Sharpe suggests, and the mechanism is the mean-reverting structure.

**Alpha decay:** IC is not constant over holding time. At entry (t=0), IC = IC_max. At t = half_life, IC ≈ 0. Measure alpha decay directly from backtest: compute IC at t=1, 2, 5, 10, half_life bars. The optimal hold period is where IC crosses zero — holding longer actively destroys value. This is a paper exhibit showing the theoretical optimum vs actual mean hold.

**Effective breadth calculation for CAMARF:**
- 6 confirmed 1h pairs: 3 bank pairs (correlated) + 3 other pairs
- Bank cluster effective BR ≈ 1.2 (not 3)
- Other pairs effective BR ≈ 3 (assumed uncorrelated)
- Total effective BR for 1h ≈ 4.2 per TF period
- Annualized at 252 daily TF periods with average 5 entries/period: BR ≈ 21

This gives: if IR = 0.8 (good strategy), IC = 0.8/√21 ≈ 0.17. A per-trade IC of 0.17 is achievable and meaningful.

### Lopez de Prado — Complete Framework

**Meta-labeling (our ML architecture):**
Stage 1 — primary model: cointegration z-score threshold (e.g., |z| > 2.0). Binary signal.
Stage 2 — meta-labeler: ML classifier predicts P(Stage 1 is correct given current features).
Entry only when meta-label probability > threshold AND primary signal triggered.
Position size ∝ meta-label probability.

This is the CAMARF ML architecture exactly. Frame it this way in the paper.

**Triple barrier labeling vs. fixed horizon:**
- Triple barrier: profit target (upper), stop loss (lower), time limit (vertical). Label = first barrier hit.
- Fixed horizon: label = outcome at N bars regardless of path.
- Triple barrier is superior: captures that a trade hitting a stop loss at bar 8 then recovering at bar 26 is a FAILED trade, not a "strong_converge" trade.
- Both tested in ml.py for comparison (confirmed implementation decision).

**Feature importance hierarchy:**
1. MDI (Mean Decrease Impurity): tree-based, fast, slight bias toward high-cardinality features
2. MDA (Mean Decrease Accuracy): permutation-based, model-agnostic, slower but unbiased
3. SFI (Single Feature Importance): train on one feature at a time, most conservative
Report all three. Convergence across methods signals robust importance.

**HHI concentration index:**
HHI = Σ wᵢ² over bets. 
HHI=1 = one bet does everything (fragile).
HHI=1/N = equal contribution (diversified).
Report HHI for pair concentration (do 2 pairs generate 90% of P&L?), for time concentration (does 80% of P&L come from 10% of periods?), and for sector concentration (bank pairs driving results?).

### Chincarini & Kim — Full Framework

**Factor model decomposition:**
R = α + BF + ε
Where B = factor loadings, F = common factors (market, sector, style), ε = idiosyncratic.

Eigenportfolio decomposition projects out BF. EG on ε residuals tests genuine idiosyncratic cointegration. This is implemented in analysis.py as EigenportfolioDecomposer.

**Marchenko-Pastur details:**
For normalized returns matrix (N×T), the bulk of eigenvalues under H₀ (IID normal) lies in [λ₋, λ₊] where:
λ± = (1 ± √(N/T))²

For N=1536, T=16220 daily bars: λ+ = (1 + √(0.0947))² ≈ 1.61
Eigenvalues above 1.61 = genuine systematic factors (K ≈ 15-30 for S&P 1500).

**Gold vs Silver tier:**
- Gold: EG confirmed on RAW prices AND on eigenportfolio residuals → genuinely idiosyncratic
- Silver: EG confirmed on raw prices only → may be factor-driven

Silver tier pairs are still reported (they may be tradeable) but with the caveat that their cointegration may reflect shared sector exposure rather than specific business relationships.

### Ilmanen — Economic Mechanisms

**Why cross-asset cointegration persists:**
Risk premia exist because investors demand compensation for bearing specific risks. The ES↔utility cointegration at 15m exists because:
1. ES reprices macro risk at millisecond speed (most liquid instrument globally)
2. Utility stocks reprice at minute/hour speed (less liquid, indirect mechanism chain)
3. The lag = the repricing speed differential = tradeable edge
This is not statistical — it's structural. It will persist as long as liquidity differentials persist.

**Term structure of mean reversion (Ilmanen + empirical support from our results):**
- Sub-daily to weekly (minutes to days): MEAN REVERSION dominates (our 15m and 1h findings)
- Monthly (1-12 months): MOMENTUM dominates (why our 1M results are sparse)
- Multi-year: MEAN REVERSION returns (value effects)

Our finding that confirmed pairs concentrate at 15m and 1h is consistent with the academic literature on momentum/mean reversion term structure.

**Carry, value, momentum as pervasive factors:**
Every confirmed pair can be characterized by which factor drives its expected convergence:
- Value pair (JNJ↔PG): long-term earnings yield equalization
- Carry pair (ES↔utilities): yield differential and risk premium
- Momentum pair (bank cluster during stress): sector flow reversal
Understanding which factor drives each pair's expected convergence sharpens the ML feature design.

### Shreve and Hull — Mathematical Foundations

**ItÃ´'s Lemma:** for f(t, X) where X is Itô process:
df = (∂f/∂t + μ∂f/∂X + ½σ²∂²f/∂X²)dt + σ(∂f/∂X)dW

The ½σ²∂²f/∂X² term (Itô correction) appears in every options pricing formula and explains why log-normal returns have a drift adjustment of -σ²/2.

**Girsanov for options.py:** changing from P-measure (physical) to Q-measure (risk-neutral) changes Brownian drift from μ to r (risk-free rate). The market price of risk λ = (μ-r)/σ is embedded in the Radon-Nikodym derivative dQ/dP = exp(-λW_T - λ²T/2). This is how Heston model parameters under Q differ from their P-measure counterparts.

**Black-Scholes Greeks for strategy Greeks:**
- Δ = ∂V/∂S: hedge ratio — maintain by delta-hedging the spread position
- Γ = ∂²V/∂S²: convexity — measure of how fast hedge needs rebalancing
- ν (vega) = ∂V/∂σ: spread vol sensitivity
- θ (theta) = -∂V/∂t: daily P&L decay from time passing without convergence

### Synthetic Bars (Planned — v2)

Dollar bars (Lopez de Prado) sample when $X of notional trades, not at fixed time intervals. This produces bars with approximately constant variance regardless of trading intensity — far better statistical properties than time bars. For CAMARF, this requires 1m OHLCV as the base (approximate dollar bar reconstruction) or actual tick data. The key improvement: ML features computed on dollar bars have near-IID variance, eliminating the need for heteroscedasticity corrections and making standard statistical tests valid. Noted as a significant future extension.

### Session Log Update

### Session 3 (2026-06-15, morning)
- Cache migration v2 applied (renamed 5230 files, deleted 529 corrupted 1m/1M files)
- IBKR clientId conflict fixed (analysis.py uses clientId=2)
- ValueError f-string fixed (was killing all pair modeling at 1h/4h/1D/7D)
- _regime_worker moved to module level (was nested function, not picklable for ProcessPoolExecutor)
- Parallel regime fitting implemented (ProcessPoolExecutor, 12 workers)
- Per-TF hash checkpoint implemented (crash recovery preserves completed TFs)
- S&P 1500 universe expansion (SP400 + SP600 Wikipedia scrapers, same format as SP500)
- ETF asset class added to yfinance routing filter
- EigenportfolioDecomposer class added to analysis.py (Marchenko-Pastur K selection, factor residual computation, Gold/Silver tier assignment)
- UniverseFilter.run() updated to return matrices for EigenportfolioDecomposer reuse

### Session 4 (2026-06-15, afternoon/evening)
- IBKR degraded-mode batch yfinance fallback: rolling failure rate tracker (10-request window, 70% threshold), 90s pause then batch yfinance for all remaining assets in TF
- Intraday retry waits reduced from (5,10,20,40s) to (3,5,10s) for faster failure detection
- IBKR upgrade queue: assets where yfinance gave truncated history flagged for IBKR re-try after main sweep
- DataStore.is_data_sufficient(): bar count quality gate (e.g. 8h minimum 4000 bars — catches yfinance 1458 < IBKR 5861)
- Data integrity principle: never overwrite good data with equal or worse data; only repave if missing, wrong frequency, or insufficient bar count
- 3M (quarterly) and 6M (semi-annual) TFs added via resample from 1D
- DataStore._TF_SAFE updated for 3M→"3mo" and 6M→"6mo"
- Cache migration v3: also deletes corrupted 2m/3m derived files
- Comprehensive DEVELOPMENT.md update with all concepts, authors, frameworks

### Next Session
- Verify overnight run results: check pairs.parquet for all TFs
- Check eigenportfolio Gold/Silver tier distribution
- Check Hurst values for confirmed pairs (should be < 0.50 for OU processes)
- Check SP400/SP600 scraper success (look for "S&P MidCap 400: N tickers" in log)
- Implement Granger causality (stats.py) for all confirmed pairs
- Begin ml.py architecture design with triple-barrier labeling

---

## Bug Registry Addendum

**BUG-D16: ETF class not in yfinance routing filter**
Root cause: `yf_assets` filter included `("equity","crypto","forex")` but not `"etf"`. ETFs added to `_build_raw_list` were silently dropped from Phase 1 yfinance fetch.
Fix: add `"etf"` to filter. QQQ, IWM, SPY, VOO, GLD, SLV, USO now correctly fetch.

**BUG-A08 (updated name): Nested _fit_one_regime**
Root cause: regime worker function defined inside `_run_one_tf` as local function. ProcessPoolExecutor requires picklable functions; local/closure functions are not. Would have raised `AttributeError: Can't pickle local object` on first parallel regime fitting call.
Fix: `_regime_worker()` moved to module level in analysis.py.

**BUG-D17: 2m/3m derived from corrupted 1m data**
Root cause: the 1m/1M Windows filename collision caused monthly data to overwrite 1m cache. The `Deriving 2m and 3m from 1m bars` step then resampled monthly data to "2m" and "3m", producing cache files with 31-day gaps labeled as 2-minute bars.
Fix: cache migration v3 also deletes `*_2min.parquet` and `*_3min.parquet` so they get re-derived from clean 1m data after re-fetch.

**BUG-A09: INCLUDE_QQQ_EXTRAS, RUSSELL_TOP_N, INCLUDE_BRK_HOLDINGS missing from Config**
Root cause: referenced in code but never declared in `UniverseConfig` dataclass. Would raise `AttributeError` on first build attempt.
Fix: all three added to config.py with appropriate defaults.

---

## Handoff Protocol

This document serves as the complete handoff for CAMARF. A new session can reconstruct the full project context from this file alone. The key sections are:

1. **Research thesis** — what we're testing and why (see top of document)
2. **Architecture principles** — the non-negotiable design rules
3. **Bug registry** — every bug found, root cause, and fix (prevents re-introducing)
4. **Methodological decisions** — every design choice with justification
5. **Session log** — chronological record of what changed each session
6. **Planned implementations** — full outlines for ml.py, backtest.py, stats.py, options.py, report.py
7. **Next session** — specific first tasks at bottom of each session entry

**Current state before starting a new session:** read the most recent Session Log entry and "Next Session" items. The current file state is always the latest output from the previous session.

**Run diagnostics (added Session 5, refined Session 7):** `data.py` writes
`latest_run_data.log` and `analysis.py` writes `latest_run_analysis.log` to the
project root after every run — compact, structured, LLM-readable summaries
(universe counts, per-TF fetch/save diagnostics, confirmed pairs, errors). Upload
these directly at the start of a new session instead of pasting raw console output;
they're designed to be self-sufficient for diagnosis without needing a separate
summarization pass. When something breaks mid-run, the relevant console excerpt
(the actual error/traceback) is still useful alongside the summary log, since the
summary only reflects a run that reached completion.

---

## Session 5 — Data Pipeline Stabilization and Alignment System

### Session 5 Bug Registry

**BUG-D18: Batch yfinance saves 0/N bars**
Root cause: batch fallback called `YFinanceFeed.get_equity_history()` which only returns `"1D"` data keys (we removed `"1wk"` and `"1mo"` from `_YF_INTERVALS`). Then looked up `sym_data.get("8h")` — a key that never exists in the returned dict. `n_saved` always stayed 0 across all 5 intraday TFs.
Fix: batch fallback replaced with `get_intraday_fallback(sym, cls, tf_label)` which reads from `_YF_INTRADAY_MAP` and downloads the correct yfinance interval per TF.

**BUG-D19: IBKR session-dead reconnection infinite loop**
Root cause: `reconnect()` returned False and set `_session_dead = True`, but a second disconnect (or any subsequent asset failure) called `reconnect()` again — starting another 30-minute retry cycle. With 5-7 intraday TFs remaining, this burned 2.5-3.5 hours of pure waiting.
Fix: `reconnect()` checks `if self._session_dead: return False` immediately at entry. Mid-TF per-asset check also reads `_session_dead` before calling `get_bars()`.

**BUG-D20: Config hash forces full re-fetch on every config change**
Root cause: `ProgressLogger.is_complete()` compared the stored config hash to the current hash. Any config change (adding new parameters, new TF labels, etc.) marked ALL 1,500 assets as stale, causing a 2+ hour full re-fetch even when cached data was perfectly valid.
Fix: when hash differs, `is_complete()` now checks `DataStore.is_fresh(sym, "1D")` and `DataStore.is_data_sufficient(sym, "1D")`. If daily data is fresh and sufficient, silently update the stored hash and return True. Only re-fetch if data is genuinely missing or outdated.

**BUG-D21: analysis.py running full IBKR fetch (incorrect architecture)**
Root cause: `analysis.py` called `builder.build()` with `connect=True` (default), triggering a full Phase 2 IBKR intraday sweep identical to `data.py`. This re-did all IBKR work with the old broken batch code, adding hours of wasted time.
Fix: `analysis.py` now calls `builder.build(connect=False)`. analysis.py is a consumer of cached data only. data.py fetches; analysis.py analyzes. These responsibilities must never overlap.

**BUG-A10: NameError `_canonical_cutoff` not defined**
Root cause: `_canonical_cutoff = compute_canonical_cutoff(tf_label)` was placed AFTER the session-dead `continue` statement in the per-TF loop. The session-dead path calls `continue` before the assignment, so `_canonical_cutoff` was never set for subsequent code in the loop. Also, the upgrade queue section runs after the TF loop closes — any reference there would always be out of scope.
Fix: `_canonical_cutoff` computation hoisted to the very first line of each TF iteration, before ANY conditional code. Upgrade queue save no longer references `_canonical_cutoff`.

**BUG-A11: _fit_one_regime nested function not picklable**
Root cause: `_fit_one_regime` was defined as a local function inside `_run_one_tf`. ProcessPoolExecutor requires module-level picklable functions — local/closure functions always fail with `AttributeError: Can't pickle local object`.
Fix: renamed to `_regime_worker` and moved to module level in analysis.py.

### Data Pipeline Architecture (Finalized)

**data.py responsibilities (ONLY):**
- Fetch and cache all OHLCV data for all assets across all TFs
- Apply DataCleaner (standardize, gap-fill, roll-adjust)
- Apply GapFlag classification (NONE/FILL/NO_ACTIVITY/HALT/DATA_GAP/SPARSE)
- Apply timestamp snapping (open-of-bar convention, Eastern time, tz-naive)
- Apply canonical cutoff truncation (all assets aligned to same last complete bar)
- Write to DataStore cache (parquet files with safe TF names)
- Run IBKR upgrade queue after main sweep
- Never run analysis

**analysis.py responsibilities (ONLY):**
- Load universe from DataStore cache via `builder.build(connect=False)`
- Run all analysis pipeline stages
- Never fetch new data from IBKR or yfinance
- Never write to DataStore cache

### IBKR Historical Data Pacing — Ground Truth

IBKR enforces hard limits on `reqHistoricalData()`:
- Max 50 simultaneous requests
- Max 60 requests per 10-minute window per identifier type
- Pacing violations cause connection drops and Warning 2110

With 1,500 assets × 7 intraday TFs = 10,500 requests, pacing violations are inevitable. The correct architecture accepts this:
1. Fetch as much as IBKR allows before the 70% failure rate threshold
2. When degraded (>70% failure over last 10 requests), switch immediately to batch yfinance
3. If TWS crashes (TimeoutError on reconnect), set `_session_dead = True` and route all remaining TFs to yfinance immediately
4. IBKR upgrade queue retries after the main sweep when congestion clears (for deeper history)

**conId caching (planned improvement):** caching the IBKR contract ID (conId) for each symbol eliminates the internal string→contract resolution step on every request. Saves ~0.5-1s per request → ~750-1500s total for 1,500 assets. Implement as a JSON file populated the first time each symbol is successfully fetched.

### Data Alignment System (New — Session 5)

**Problem:** A 2-hour intraday sweep means assets fetched first and last have different trailing bars. Additionally, IBKR stamps intraday bars at bar open while yfinance sometimes uses bar close — creating an off-by-one-bar lag in cross-source correlations that directly contaminates cross-asset pair findings (ES↔utility 15m).

**Three-function solution:**

`compute_canonical_cutoff(tf_label)` — called once per TF at sweep start. Floors current time to last complete bar boundary:
- During session at 11:47 AM on 1h TF: cutoff = 10:30 AM (last closed bar)
- Pre-market: previous session's last bar
- Post-market: today's last bar

`snap_timestamps(df, tf_label, source)` — normalizes all bar timestamps to open-of-bar convention, Eastern time, timezone-naive:
- 1h bar at 10:30 (yfinance close-stamp) → snapped to 09:30 (open-stamp, matching IBKR)
- Bars outside session window are dropped
- Deduplicates after snapping (keep last)

`truncate_to_cutoff(df, cutoff)` — drops bars after the canonical cutoff. Ensures first and last assets in sweep share identical last bars.

**Applied at:** every save point in the intraday sweep (IBKR fetch, per-asset yfinance fallback, batch yfinance fallback, dead-session yfinance batch). NOT applied in upgrade queue (runs after loop, different scope).

### GapFlag System (New — Session 5)

Every aligned bar carries a `gap_flag` integer column:
- `0` NONE — clean bar
- `1` FILL — ≤5 bar gap, forward-filled. Include in EG/corr; exclude from ML volume features
- `2` NO_ACTIVITY — crypto genuine zero-trade. Include price and volume=0 as-is
- `3` HALT — trading halt. Price forward-filled; volume invalid
- `4` DATA_GAP — >5 bar gap. Price forward-filled for continuity; MASKED to NaN in EG and correlation. The large return spanning a long gap would inflate ADF statistics toward false unit-root rejection
- `5` SPARSE — thin liquidity / pre-IPO period. Include with lower weight

`_gap_aware_returns(df)` — masks DATA_GAP bars to NaN before computing log returns (used in `build_returns_matrix`)
`_clean_close(df)` — masks DATA_GAP close prices to NaN (used in `_build_log_price_map` for EG)

### Gemini's IB Gateway Advice — Assessment

Gemini correctly said: stay with IB Gateway (not Web API). The Web API has worse pacing limits and requires session keep-alive daemons.

Gemini's other advice (`reqPositions()`, `reqMktData()`) is for reading live account positions and streaming real-time quotes — not relevant to CAMARF which uses `reqHistoricalData()` exclusively.

The `conId` caching advice IS applicable and worth implementing: it eliminates the internal symbol→contract resolution per request.

The fundamental bottleneck (pacing limits on 10,500 historical data requests) cannot be solved architecturally. The batch yfinance fallback is the correct solution.

### Session 5 Log

2026-06-16:
- Fixed BUG-D18: batch yfinance saves 0 bars (get_equity_history → get_intraday_fallback)
- Fixed BUG-D19: IBKR infinite reconnection loop (session_dead early-exit in reconnect())
- Fixed BUG-D20: config hash forces full re-fetch (DataStore.is_fresh check in is_complete())
- Fixed BUG-D21: analysis.py doing IBKR fetch (build(connect=False))
- Fixed BUG-A10: NameError _canonical_cutoff (hoisted to top of TF iteration)
- Fixed BUG-A11: _fit_one_regime not picklable (moved to module level as _regime_worker)
- Added GapFlag system: 6-code gap classification, gap-aware returns, clean close
- Added data alignment system: canonical cutoff, timestamp snapping, truncation
- Added DataStore.is_data_sufficient() bar count quality gate
- Added IBKR upgrade queue for assets with insufficient cached history
- Added 3M and 6M TFs (quarterly/semi-annual from 1D resample)
- S&P 1500 universe: 1506 equities + 33 non-equities ≈ 1539 candidates
- ETF asset class routing fix (ETFs were silently dropped from yfinance fetch)
- EigenportfolioDecomposer added to analysis.py (Marchenko-Pastur, Gold/Silver tiers)
- Parallel regime fitting via ProcessPoolExecutor (_regime_worker at module level)
- Per-TF hash checkpoint for crash recovery

### Next Session (after data.py run completes cleanly)

1. Read pairs.parquet for all TFs — verify BUG-A09 f-string fix produced PairResult objects
2. Check eigenportfolio Gold/Silver tier distribution
3. Check Hurst values for confirmed pairs (H_rs < 0.50 for OU processes)
4. Check SP400/SP600 Wikipedia scraper counts in log
5. Begin Granger causality implementation in stats.py (all confirmed pairs, bidirectional)
6. Design ml.py labeling: triple-barrier (primary) vs fixed-horizon (comparison)
7. VolumeStructure feature volatility standardization audit (12 features, all must be dimensionless)

---

## Planned Module: analyzer.py — Pair Characteristics Analyzer

### Concept

For each confirmed pair, identify which specific observable conditions at entry predict the best outcomes for *that pair specifically*. Not a global "what makes pairs work" analysis — a per-pair conditional attribution system.

The key insight: the same pair behaves differently under different conditions. NTRS↔STT in a high-vol banking stress environment may mean-revert in 8 bars. The same pair during a low-vol trending market may have near-zero spread (nothing to trade) or a trending spread (fundamental repricing, not noise). The analyzer finds the specific combination of conditions that characterize each pair's "best self."

This is genuinely novel in the statistical arbitrage literature. Most pairs trading papers report global backtest statistics. Reporting pair-level conditional characteristics is a meaningful methodological contribution to the paper.

---

### Architecture

**Two phases — pre-backtest (analysis.py data) and post-backtest (trade log):**

Phase 1 (pre-backtest, available now from analysis.py):
- Spread quality across regimes: does Hurst improve in specific regimes for this pair?
- Half-life stability: does half-life vary by regime or volatility environment?
- Cointegration fraction rolling: is the relationship stable or episodic?
- Spread volatility profile: when is the spread wide enough to trade but not breaking down?
- Eigenportfolio tier interaction: do Gold-tier pairs show better regime consistency?

Phase 2 (post-backtest, requires backtest.py trade log):
- Conditional P&L by regime at entry
- Conditional P&L by Hurst quintile at entry
- Conditional P&L by time-of-day at entry
- Conditional P&L by spread z-score magnitude at entry
- Conditional P&L by both legs' individual trend direction
- Conditional P&L by sector ETF context (XLF for banks, XLU for utilities, etc.)
- Conditional P&L by market breadth (SPY vs 20-day MA)
- Failure mode characterization: which conditions produce long holds, high MAE, stop-outs

---

### Core Analysis: Decision Tree Over Entry Conditions

Use a decision tree (depth 3-4 max) fitted on entry features → binary outcome (win/loss or Sharpe contribution). The tree auto-discovers which combinations of conditions matter most for this specific pair.

**Why tree-based (not regression):**
- Captures non-linear interactions (high_vol AND H < 0.40 is much better than either alone)
- Interpretable: produces explicit if-then rules ("if regime=high_vol and H<0.42: win rate 89%")
- Naturally handles categorical features (regime labels) and continuous features (Hurst, z-score)
- Low depth (3-4) forces parsimonious rules, limits overfitting

**Overfitting / Bias Controls (critical):**
- Minimum N per leaf: 10 trades (never report a characteristic based on fewer than 10 observations)
- Permutation test: shuffle trade outcomes, refit tree 1000 times, report only characteristics that exceed the 95th percentile of the null distribution
- Hold-out validation: split the trade log chronologically (first 60% for tree fitting, last 40% for validation). A characteristic is "confirmed" only if the win rate in the hold-out period is within 15pp of the in-sample rate
- Report N for every cell — a condition with N=8 is noise, N=40 is signal
- Flag pairs where the optimal condition N < 10 as "insufficient data for characteristics analysis"
- Cross-pair consistency check: a characteristic that appears for 10+ pairs is more credible than one appearing for 1 pair

**What to report PER PAIR:**
1. Single-feature breakdowns (regime, Hurst quintile, time of day, z-score magnitude)
2. Top-3 two-feature combinations (regime × Hurst, regime × time, etc.)
3. The optimal condition combination (best Sharpe leaf of the decision tree)
4. The failure mode conditions (worst Sharpe leaf — when NOT to trade)
5. Regime sensitivity score: (best_regime_Sharpe - worst_regime_Sharpe) / mean_Sharpe
   A score near 0 = regime-robust pair. Score > 2 = regime-sensitive pair.

---

### Primary Visualization: 2D Heatmap per Pair

X-axis: Hurst quintile at entry (Q1=most mean-reverting to Q5=least)
Y-axis: Regime at entry (high_vol, mean_reverting, trending, low_vol)
Cell color: Sharpe ratio
Cell annotation: N trades, Win %

```
NTRS↔STT — Entry Condition Heatmap
              Q1 (H<0.35) | Q2 | Q3 | Q4 | Q5 (H>0.47)
high_vol      [  2.6  ]   [2.1][1.4][0.8][  0.2  ]
mean_reverting[  2.1  ]   [1.7][1.1][0.5][ -0.3  ]
trending      [  0.9  ]   [0.4][0.1][-0.4][ -1.1  ]
low_vol       [  0.5  ]   [0.2][-0.1][-0.5][ -1.3  ]
```

Secondary heatmaps (if N sufficient):
- Regime × time-of-day
- Z-score magnitude × Hurst
- Sector ETF trend × regime

---

### Cross-Pair Comparison Output

After running the analyzer across all confirmed pairs:

1. **Regime-robust pairs**: pairs where Sharpe > 1.0 in ALL regimes
   → Highest quality; use in all market conditions

2. **Regime-sensitive pairs**: pairs where Sharpe > 1.5 in best regime, < 0.5 in worst
   → Require ML meta-labeler to gate entries on regime

3. **Characteristic universality**: if a condition (e.g., "H < 0.40 at entry improves results") appears for >60% of confirmed pairs, it's a universal signal quality indicator, not pair-specific noise
   → This becomes a global filtering rule in the ML layer

4. **Cross-pair characteristic correlation**: do pairs that share a sector (e.g., all bank pairs) share the same optimal conditions?
   → Evidence of structural vs idiosyncratic co-movement

---

### Failure Mode Analysis

Equally important: characterize when the pair BREAKS DOWN.

For each confirmed pair, identify:
- Which conditions produce the longest hold times (spread takes too long to converge)
- Which conditions produce the highest MAE (spread widens dramatically before reverting)
- Which conditions produce actual stop-outs (spread never converges)

The failure leaf of the decision tree is the "do not trade" signal. In the ML meta-labeler, this becomes a negative class label:
- "NTRS↔STT in trending regime with H > 0.45: stop-out rate 34%, mean MAE -2.8%"
- "FITB↔KEY during earnings season: convergence failure rate 61%"

**Bias awareness:**
- The failure mode analysis uses the same data as the success analysis → double-dipping on the same sample
- Mitigation: use chronological hold-out for validation of both success AND failure conditions
- The permutation test for failure modes uses the same null distribution as for success
- Never report a failure condition as confirmed if N < 10 in the validation period

---

### Integration with Paper

In the research paper, this becomes the "Strategy Characteristics" section:
- Reports confirmed pair-level conditional Sharpe matrices
- Shows regime sensitivity distribution across the pair universe
- Demonstrates that H_rs at entry is predictive of convergence quality (or not — either result is meaningful)
- Provides evidence that the ML meta-labeler has learnable signal structure

The negative results (pairs that don't show identifiable characteristics) are also interesting for the paper — they suggest those pairs' cointegration is genuinely robust and not condition-dependent.

---

### Implementation Notes (when building)

- `analyzer.py` imports from `analysis.py` (pair metadata, spread series, regimes) and `backtest.py` (trade log)
- Decision tree: `sklearn.tree.DecisionTreeClassifier(max_depth=4, min_samples_leaf=10)`
- Heatmap: matplotlib with `seaborn.heatmap` or `plt.imshow` + custom annotations for N and Win%
- Feature engineering happens in the analyzer, not in backtest.py — backtest.py only logs raw entries/exits
- The analyzer should be runnable incrementally: as more pairs accumulate in the backtest, characteristics sharpen
- Output: one PDF per confirmed pair (the "characteristics card") + one cross-pair summary PDF

---

### Prerequisites Before Building

1. data.py and analysis.py running cleanly with confirmed pairs
2. backtest.py implemented with per-trade logging (entry conditions captured at entry time)
3. At least 20 confirmed pairs with 30+ trades each (minimum statistical power for tree fitting)
4. Chronological split validation requires sufficient trade history (at least 2 years of backtest data preferred)


---

## Session 6 — Analysis Pipeline Stabilization and Methodological Extensions

### Session 6 Bug Registry

**BUG-A12: `_clean_close` NameError kills all EG testing**
Root cause: `_clean_close` and `GapFlag` were defined in `data.py` but never imported into `analysis.py`. Every TF's EG test crashed with `NameError: name '_clean_close' is not defined` in `CointScanner._build_log_price_map`. This produced zero pairs/trios/regimes for all TFs in both analysis.py runs.
Fix: added `GapFlag`, `_gap_aware_returns`, `_clean_close` to the `from data import (...)` block in analysis.py.

**BUG-D22: 8h batch yfinance saves 0/N (persistent)**
Root cause: `snap_timestamps(df, "8h")` with `bar_mins=390` maps ALL intraday bars to 9:30 AM (the only valid 8h boundary in a 6.5h session), creating hundreds of duplicates per day. After dedup, ~1 bar/day. This was not causing 0 saves by itself, but 8h is analytically equivalent to 1D and carries no independent value. The TF was also causing frequency validator confusion and wasted IBKR pacing budget.
Fix: 8h removed entirely from all TF constants, maps, IBKR sweep, and resample functions. 13 TFs remain: 1m, 2m, 3m, 5m, 15m, 30m, 1h, 4h, 1D, 7D, 1M, 3M, 6M.

**BUG-D23: 1h cache contaminated with 8h-frequency data (961 assets)**
Root cause: previous batch yfinance fallback bug wrote 8h-frequency data (one bar per day, ~82800s median gap) to 1h cache files for ~961 assets. DataStore.validate_frequency() correctly detected and skipped these but the data was still on disk.
Fix: `DataStore.clear_tf_cache("1h")` added as a utility method. Run once before next data.py execution to purge the contaminated files. The fresh 1h fetch will use the corrected batch fallback.

**Note:** User deleted the entire cache on 2026-06-17. Next data.py run starts completely fresh — no contamination issue, no migration needed.

### Data Pipeline Changes (Session 6)

**8h removed from all constants and code:**
- `DataStore._TF_SAFE`: removed `"8h": "8hr"`
- `DataStore._EXPECTED_GAP_SECONDS`: removed `"8h": 28800`
- `DataStore._MIN_BARS`: removed `"8h": 4000`
- `DataAligner.align_intraday.freq_map`: removed `"8h"`
- `_TF_MINUTES` (canonical cutoff): removed `"8h": 390`
- `YFinanceFeed._YF_INTRADAY_MAP`: removed `"8h"` entry
- `IBKRFeed.INTRADAY_TFS`: removed `("8 hours", "8h", "10 Y")`
- `YFinanceFeed._resample_from_daily`: removed 8h resample block
- Active TF count: 13 (was 14)

**Dual-failure retry system:**
When both IBKR and yfinance fail for an asset-TF combination during the sweep, the asset-TF is queued in `_dual_fail_queue`. After all TFs complete and before the upgrade queue runs, one retry pass attempts yfinance again for all dual-failed assets. IBKR will have recovered from pacing congestion; yfinance from transient rate limiting.

Persistent failure tracking in `output/cache/persistent_failures.json`. Format: `{"SYMBOL:tf": N}` where N = number of consecutive full-run failures. When a symbol's total failure count across all TFs reaches `UniverseBuilder._PERSISTENT_FAIL_THRESHOLD = 3`, it is auto-added to the exclusion list with reason "Auto-excluded: N total TF failures."

**Exclusion list reset (2026-06-17):**
Cleared dynamic exclusions accumulated during unstable IBKR sessions. Retained hardcoded known-unavailable: `VLTO` (Veralto spinoff — no intraday data), `BNY` (use "BK" instead), `FDXF` (no data from any source).

**`DataStore.clear_tf_cache(tf_label, dry_run=False)`:**
Deletes all parquet files for a specific TF without touching others. Use when a TF cache is contaminated (wrong frequency, wrong data). Pass `dry_run=True` to count files without deleting.

### Episodic Cointegration and Survivorship Bias

**The problem:** Standard EG test over the full historical window finds cointegration if the relationship held for any sufficiently long subperiod, even if it broke down completely afterward. A pair cointegrated 2010-2015 but not since will pass the full-sample EG test, produce excellent backtest results over the integration period, and generate losses live.

**Primary defense: `coint_fraction_rolling`**
Already in `PairResult`. Measures the fraction of rolling 252-day windows where the pair passes EG at the 5% level. A pair cointegrated 2010-2015 out of a 2005-2025 sample would show `coint_fraction_rolling ≈ 0.25` (5 of 20 years). Filter threshold: require `coint_fraction_rolling ≥ 0.70` for inclusion in the confirmed pair universe. This filters historical-only cointegration without requiring any architectural changes.

**Secondary defense: walk-forward validation structure**
Backtest trains on data through time T, tests on data after T. If cointegration broke before T, the OOS test catches it. If it broke after T (post-test period), no test can prevent that — it is the fundamental limitation of all statistical arbitrage, not a fixable bias. Document explicitly in the paper.

**Stress test approach (future implementation in stats.py):**
For each confirmed pair, run EG on successive non-overlapping 252-day windows and produce a binary cointegration timeline: integrated (1) or not integrated (0) for each window. Plot as a binary time series per pair. Classify pairs by stability pattern:
- "Stable current": cointegrated in the last 3+ years continuously → highest quality
- "Recovered": was not cointegrated for 1-2 years, now re-cointegrated → acceptable with monitoring
- "Historical episode": cointegrated 5+ years ago, not recently → exclude regardless of full-sample EG result
- "Episodic": alternates between integrated and not → likely sector rotation or regime-dependent; require `coint_fraction_rolling ≥ 0.85`

This timeline visualization becomes Exhibit X in the paper: "Cointegration Stability Profiles for Confirmed Pairs."

### Planned: FRED Macro Regime Context

**Why it matters for the paper:**
If NTRS↔STT only works when the yield curve is steepening, the strategy is a yield curve bet expressed through bank stocks — not genuine pairs alpha. Splitting backtest results by macro regime proves (or disproves) that the strategy is robust across economic environments. A regime-robust strategy is a much stronger claim than aggregate performance.

**Implementation: `macro.py` (new module)**
Fetch at daily frequency via `fredapi` (free, requires API key) or direct FRED CSV download:
- `T10Y2Y`: 10Y-2Y Treasury spread (yield curve shape)
- `BAMLH0A0HYM2`: HY-IG credit spread (credit risk appetite)
- `VIXCLS`: VIX daily close (equity volatility regime)
- `FEDFUNDS`: Fed Funds rate (monetary policy stance)
- `DCOILWTICO`: WTI crude oil (commodity/inflation regime)
- `CPIAUCSL`: CPI monthly (inflation regime, monthly frequency)
- `USREC`: NBER recession indicator (binary, monthly)

Macro regime classification (for each trading date):
- Yield curve: steep (T10Y2Y > 1.5%), normal (0-1.5%), flat/inverted (< 0%)
- Credit: tight (spread < 300bp), normal (300-500bp), wide (> 500bp)  
- Volatility: low (VIX < 15), normal (15-25), high (> 25), crisis (> 35)
- Recession: NBER expansion vs contraction

Integration with analyzer.py:
Each trade entry is tagged with the macro regime at that date. `PairCharacteristicsAnalyzer` includes macro regime as an additional dimension in the conditional performance matrix. Enables: "NTRS↔STT performs best in high-vol + tight credit + steep yield curve" — a complete macro context for the strategy.

Paper contribution: "Strategy robustness across macro regimes" section showing Sharpe by regime combination. Regime-robust pairs are preferred over regime-sensitive pairs for live deployment.

**Implementation effort:** ~1 day. `fredapi` or direct HTTP CSV fetch; daily alignment to trading calendar; regime binning; integration with backtest trade log.

### Planned: Sentiment Analysis (Future Work)

Two approaches considered:
1. **Per-leg sentiment divergence** (useful): NLP on earnings calls, news, 8-Ks for each pair leg. When one leg has strongly positive sentiment and the other neutral, spread widening may be fundamental repricing, not tradeable noise. This signal conditions when to trade vs avoid a spread.
2. **Aggregate market sentiment** (noisier): fear/greed indexes, social media tone. More crowded signal, harder to justify in academic paper.

Decision: FRED macro context (above) is higher priority for the paper. Per-leg sentiment divergence is in "future work" — it would require a substantial NLP pipeline and the payoff in the paper is lower than macro regime robustness. Aggregate sentiment analysis not planned.

### Session 6 Log

2026-06-17:
- Fixed BUG-A12: _clean_close NameError (import added to analysis.py)
- Fixed BUG-D22: 8h TF removed entirely from all data.py constants and analysis.py
- Fixed BUG-D23: DataStore.clear_tf_cache() utility added for targeted cache purge
- Added dual-failure retry system with persistent failure tracking and auto-exclusion
- Reset exclusion list (cleared session-accumulated dynamic exclusions)
- Cache fully deleted by user — next run starts completely fresh
- Documented episodic cointegration methodology and coint_fraction_rolling defense
- Designed FRED macro regime module (macro.py) — planned post-backtest implementation
- Documented sentiment analysis as future work (per-leg divergence, not aggregate)
- Added analyzer.py full design (conditional performance attribution per pair)

### Next Session (after data.py runs cleanly)

1. Verify 0 frequency mismatches in analysis.py log (1h cache was fully deleted, fresh fetch)
2. Verify EG testing runs without NameError (BUG-A12 fixed)
3. Check confirmed pairs across all TFs — expect results at 15m, 1h, 4h, 1D, 7D
4. Verify coint_fraction_rolling filter (≥ 0.70) is applied before pair confirmation
5. Add FRED macro regime fetch to macro.py (one session)
6. Begin stats.py: cointegration stability timeline per confirmed pair
7. Begin backtest.py architecture once confirmed pairs are stable


---

## Planned Enhancement: Rich Regime Classification for Entry/Exit Gating

### Concept

The current HMM/GMM regime classification discovers hidden states without semantic labels.
The enhancement adds economically interpretable regime layers at three levels:

**Level 1 — Individual leg regimes (per asset)**
- Directional: bull (persistent uptrend), bear (persistent downtrend), neutral (range-bound)
- Structure: trending (H_rs > 0.55, ADX > 25) vs mean-reverting (H_rs < 0.45)
- Volatility: low, normal, elevated, crisis (relative to asset's own vol history)

**Level 2 — Spread regimes (per pair)**
- Spread structure: compressing (consolidating), ranging (tradeable), widening (trending), breaking (breakdown)
- Spread vol regime: spread volatility relative to its own history
- Cointegration strength: rolling Johansen test p-value trend — is the relationship strengthening or weakening?

**Level 3 — Macro overlay (from macro.py)**
- Yield curve regime: steep, normal, flat/inverted
- Credit regime: tight, normal, wide, stressed
- Equity vol regime: VIX < 15 (calm), 15-25 (normal), 25-35 (elevated), > 35 (crisis)
- Business cycle: NBER expansion vs contraction

---

### Why This Matters for Pairs Trading Specifically

Pairs trading works when spread mean reversion is reliable. Mean reversion requires
the spread to be stationary, which breaks when either leg trends independently.

**The interaction that matters:**
- Both legs in mean-reverting regime + spread consolidating + macro calm → ideal entry
- One leg trending + spread widening → do not enter (not mean reversion, fundamental repricing)
- High vol macro regime + bank pairs → spread widens more but also reverts more strongly
  (stress-driven divergence, not fundamental repricing)
- Yield curve inversion + bank pairs → cointegration weakens (NIM compression affects legs
  differently based on liability/asset duration mix)

This is not cosmetic — it directly explains when the strategy is theoretically valid
and when it isn't. A pair with coint_frac=1.00 in a low-vol macro regime may have
coint_frac=0.60 in a credit-stress regime. Knowing this changes position sizing,
entry thresholds, and stop-loss design.

---

### Implementation Design (for analyzer.py / ml.py build session)

**Features to compute per entry signal:**

Leg-level:
- `leg_a_hurst`, `leg_b_hurst` — rolling 60-day Hurst on each leg
- `leg_a_adx`, `leg_b_adx` — Average Directional Index (trend strength)
- `leg_a_above_ma`, `leg_b_above_ma` — price vs 20-period MA (directional bias)
- `leg_a_vol_pctile`, `leg_b_vol_pctile` — realized vol percentile vs own history

Spread-level:
- `spread_bb_width` — Bollinger Band width (consolidating = low, breaking = high)
- `spread_atr_pctile` — ATR relative to its own history
- `spread_vel` — spread velocity (rate of change, positive = widening, negative = compressing)
- `spread_zscore_mag` — |z-score| at entry (too wide may be fundamental, not noise)
- `spread_johansen_pval_trend` — is rolling Johansen p-value improving or worsening?

Macro (from macro.py FRED data aligned to trading dates):
- `yield_curve_regime` — categorical: steep/normal/flat/inverted
- `credit_regime` — categorical: tight/normal/wide/stressed
- `vix_regime` — categorical: calm/normal/elevated/crisis
- `recession_flag` — NBER binary

**HMM state labeling:**
After the existing HMM discovers hidden states, post-hoc label each state using:
- Modal directional regime of its member bars
- Modal spread structure
- Modal macro context
This connects the statistical states to economic interpretation without requiring
the HMM to be explicitly informed by these labels (preserving unsupervised discovery).

---

### Research Contribution for Paper

Current literature: most pairs trading papers test cointegration, find a threshold rule,
backtest. Regime conditioning is rare, macro-aware pairs strategies are rarer.

CAMARF contribution:
1. Show HMM-discovered states correspond to economically meaningful regime combinations
2. Show conditional Sharpe (high_vol + mean-reverting + spread_compressing) >> unconditional
3. Show which regime combinations produce the failure modes (trending + credit_stress)
4. Demonstrate that the ML meta-labeler is implicitly learning these regime combinations
   (SHAP analysis of feature importance)

This turns the paper from "here's a cointegration-based strategy" to "here's a regime-aware
conditional statistical arbitrage framework with economic grounding" — substantially stronger
for MFE applications.

---

### Implementation Sequence

1. macro.py FRED data fetch (1 day, can run before backtest.py)
2. Leg-level features (in analysis.py PairResult, 1 day)
3. Spread-level features (in analysis.py SpreadModel, 1 day)
4. HMM state labeling (in analysis.py RegimeClassifier, 0.5 days)
5. All features available as conditioning variables in analyzer.py decision tree
6. Full paper exhibit: 3D conditional Sharpe matrix (macro × spread structure × Hurst)

### Prerequisites

- Confirmed stable pair universe (currently building)
- backtest.py trade log (needed for outcome variables in analyzer.py)
- macro.py FRED fetch (independent of backtest)


---

## Session 7 — yfinance Reliability Overhaul (data.py Stabilization)

### Context

This session was almost entirely spent making `data.py`'s Phase 2A (yfinance intraday
sweep) reliable. What looked like one problem ("data won't fetch") turned out to be
six distinct, unrelated bugs discovered one at a time through log evidence. Documented
here in full so the debugging sequence isn't repeated.

### Session 7 Bug Registry

**BUG-D24: 4h derivation produces silent wrong-frequency output**
Symptom: `[4h] derived: 4 saved | 0 skip_fresh | 6 no_source | 0 resample_fail | 1507 freq_invalid`
Root cause: 4h is derived by resampling cached 1h data (`df_1h.resample("4h")`). The
original code had a bare `except Exception: pass` around the resample call and no
validation of the OUTPUT frequency — if the source 1h data was itself sparse/malformed,
resample succeeded without error but produced ~1 bar/day (86400s gap) instead of the
expected 14400s.
Fix: added explicit per-stage failure counters (`skip_fresh`, `no_source`,
`resample_fail`, `freq_invalid`) and a post-resample frequency validation check
(reject if median gap > 14400×3). First-failure diagnostic captures source origin
(this-run vs disk), row count, and source's own pre-resample gap — converts silent
failure into actionable diagnosis instead of guesswork.

**BUG-D25: RunSummary table empty despite Phase 2A running**
Root cause: `_summary.record_tf()` was never called from inside Phase 2A's fetch loop
(only existed in the IBKR sweep path, which doesn't run in yfinance-only mode).
Fix: `_summary.record_tf()` wired into both the main TF fetch loop and the 4h
derivation block. `RunSummary.write()` table columns made dynamic (union of all keys
actually recorded) instead of a fixed schema, so derivation-specific diagnostics
(skip_fresh, no_source, resample_fail, freq_invalid) display alongside fetch
diagnostics (yf_ok, yf_fail) without a schema mismatch.

**BUG-D26: 2m systematic 100% fetch failure — period interpretation**
Symptom: `[2m] complete: 0/220 saved | fail_fetch=220`. Root cause investigation went
through two incorrect hypotheses before landing on the real one:
- *Wrong hypothesis 1*: yfinance's `period="60d"` means 60 trading days (~84 calendar
  days), exceeding Yahoo's 60-calendar-day API limit. Attempted fix: reduce to `"55d"`.
  Did not resolve the issue.
- *Wrong hypothesis 2*: switched from `yf.download(period=...)` to
  `yf.download(start=..., end=...)` with explicit datetime objects to eliminate any
  period-string ambiguity. This introduced BUG-D27 (below) and still didn't fix 2m.
- *Real root cause*: confirmed via user's own standalone test script
  (`yf.Ticker(symbol).history(period="60d", interval="5m")` returned 85 days/4680 rows
  successfully) that period-string interpretation was never the problem. The actual
  issue was `yf.download()` itself behaving unreliably under rapid sequential calls
  compared to `yf.Ticker().history()` — see BUG-D28.

**BUG-D27: explicit-date day-count keyed by wrong variable (introduced, then fixed, by D26's wrong-hypothesis-2 attempt)**
Root cause: the `_CAL_DAYS` lookback table built during the (later-reverted) explicit-date
experiment was keyed by `tf_label` instead of the underlying `yf_interval`. Since
`tf_label="3m"` downloads at `yf_interval="1m"` (then resamples), `_CAL_DAYS["3m"]=55`
caused a 55-calendar-day request at 1m granularity — 7× over Yahoo's hard 8-day limit
for 1m data. 100% failure for every 3m request, confirmed by the exact Yahoo error
text: `"Only 8 days worth of 1m granularity data are allowed to be fetched per
request"` on a request spanning 55 days.
Fix: this entire mechanism (`_CAL_DAYS`, explicit `start=`/`end=` dates) was removed
in BUG-D28's fix — superseded, not patched.

**BUG-D28: yf.download() unreliable for bulk sequential calls; yf.Ticker().history() is the correct API**
Root cause: empirically confirmed (not theorized) via the user's standalone test
script that `yf.Ticker(symbol).history(period=X, interval=Y)` succeeds reliably,
including for 1m (where `yf.download()` with explicit dates failed 100% of the time).
Fix: replaced `yf.download()` entirely with `yf.Ticker(yf_sym).history(period=...)`
in `get_intraday_fallback`, using the period strings already correctly defined in
`_YF_INTRADAY_MAP` (1m→5d, 3m→5d via 1m, 2m→55d, 5m/15m/30m→60d, 1h→730d). Removed
the "Yahoo session-block" pause/abandon mechanism that had been built on the wrong
diagnosis (BUG-D26 wrong-hypothesis-1) — there was no real Yahoo-side block, only a
malformed request.

**BUG-D29: stale "45d_fallback" string reaching the API as a literal period**
Symptom: `ERROR MCRI: Period '45d_fallback' is invalid, must be one of: 1d, 5d, 1mo, ...`
Root cause: a file-sync/merge artifact on the user's machine — a fragment of the
already-reverted BUG-D27 code (`_attempts.append(("45d_fallback", ...))`) survived
in the locally-saved file alongside newer code, despite the canonical version
(verified via direct grep) never containing that string. Diagnosed by MD5 checksum
comparison between the canonical file and the user's local copy.
Fix: added a defensive regex guard (`_VALID_PERIOD` pattern) validating any period
string immediately before it reaches `yf.Ticker().history()`. Any malformed value
(from any future merge/sync issue) is now caught with a clear, specific error instead
of a cryptic per-asset API failure. This is permanent insurance, not a one-time patch.

**BUG-D30: missing `pytz` dependency in the `trading` conda environment**
Symptom: `ModuleNotFoundError: No module named 'pytz'` at `import yfinance`.
Root cause: environment dependency gap, surfaced after a conda/pip upgrade. Not a
code issue.
Fix: `pip install pytz` in the `trading` environment. One-time environment fix.

**BUG-D31 (CRITICAL — root cause of the entire 1h/2m/1m failure pattern): fresh `yf.Ticker()` per call triggers Yahoo anti-bot throttling under rapid sequential calls**
Symptom: after BUG-D30's pytz fix, `yf.Ticker('SPY').history(period='730d',
interval='1h')` succeeded perfectly as a standalone interactive call (5082 rows), but
the IDENTICAL call inside Phase 2A's loop failed 100% (87/87) for completely
unremarkable, liquid tickers (A, AOS, etc.) with NO exception raised — silent empty
DataFrames.
Diagnosis: confirmed via the "works once standalone, fails 100% inside a tight loop"
signature — a well-documented yfinance 0.2.x behavior. Creating a fresh `yf.Ticker()`
object per call forces a new cookie/crumb authentication negotiation with Yahoo on
every single request. A one-off interactive call never triggers Yahoo's anti-bot
detection; a loop of hundreds/thousands of fresh `Ticker()` instantiations does,
almost immediately.
Fix: `YFinanceFeed._get_session()` creates ONE shared `requests.Session` (with a
browser-like User-Agent header) on first use, reused for the lifetime of the process.
Every `yf.Ticker()` call in `get_intraday_fallback` now passes `session=
YFinanceFeed._get_session()`. Wrapped in a `try/except TypeError` fallback to a plain
`Ticker()` call in case a yfinance version doesn't support the `session=` kwarg the
same way (some versions moved to `curl_cffi`-based sessions internally — fallback
prevents this from being a hard crash if the assumption doesn't hold for a given
version). Also added a small universal 0.15s inter-request delay across ALL intraday
TFs (not just 1m/2m, since 1h hit the identical 100%-failure signature) as
additional insurance against burst-rate triggers.

### Other Session 7 Fixes

**Pylance/type-checking cleanliness:**
- `FrozenSet` added to `typing` imports in both `data.py` and `analysis.py`
  (was being used without import — worked at runtime via duck typing but flagged
  by static analysis)
- `Any` added to `data.py`'s typing imports (used by `RunSummary.phase1` type hint)
- Cleaned up a comment in `_clean_contaminated_cache` that contained the literal
  string `_summary` and was being flagged as a false-positive undefined-variable
  reference by Pylance (it was always inside a comment, never executed)

**Retry-with-auto-exclusion system (data.py):**
Failed fetch-TF combinations are now retried up to 3 times at the end of the Phase 2A
sweep (after all TFs complete), with results persisted to
`output/cache/persistent_failures.json`. A symbol accumulating
`UniverseBuilder._PERSISTENT_FAIL_THRESHOLD` (= 3) consecutive full-run failures
across all TFs is automatically added to the exclusion list via
`UniverseBuilder.add_exclusion()`. Exclusion list was also manually reset this
session — only `VLTO`, `BNY`, `FDXF` remain as confirmed permanently-unavailable
tickers; all session-accumulated dynamic exclusions from earlier unstable runs
were cleared.

**Full Phase 2A TF coverage:**
Extended from `["5m","15m","30m","1h"]` to the complete intraday set
`["1h","30m","15m","5m","2m","1m","3m"]`, ordered longest-to-shortest depth so a
partial/interrupted run preserves the most analytically valuable data first.

**DataAligner gap-rate fix (re-confirmed working):**
The fix from Session 6 (recompute `missing` after trimming to `first_valid_index`,
rather than computing gap rate over the full 1962-present calendar) was verified via
direct synthetic test to correctly retain assets like a simulated 2013 IPO (0% gap
rate post-trim vs the previous incorrect 79%).

### Session 7 Log

2026-06-18:
- Diagnosed and fixed BUG-D24: 4h derivation silent wrong-frequency output —
  added per-stage failure counters and post-resample frequency validation
- Diagnosed and fixed BUG-D25: RunSummary table empty — wired record_tf() into
  Phase 2A, made table columns dynamic
- Diagnosed (2 wrong hypotheses, then correct) and fixed BUG-D26/D27: 2m/3m
  systematic failure — root cause was wrong-variable-keyed day-count table built
  during an unnecessary fix attempt
- Diagnosed and fixed BUG-D28 (major revert): replaced yf.download() with
  yf.Ticker().history() based on user's empirical standalone test — restored
  the pre-existing correct period strings in _YF_INTRADAY_MAP
- Diagnosed and fixed BUG-D29: stale string reaching API as literal period —
  added defensive regex validation guard, diagnosed via MD5 checksum comparison
  between canonical and user's local file
- Diagnosed and fixed BUG-D30: missing pytz dependency — environment fix, not code
- Diagnosed and fixed BUG-D31 (root cause of entire session's failure pattern):
  fresh yf.Ticker() per call triggering Yahoo anti-bot cookie/crumb throttling
  under rapid sequential calls — implemented shared requests.Session reuse
- Added retry-with-auto-exclusion system with persistent_failures.json tracking
- Reset exclusion list to only confirmed-permanent unavailable tickers
- Extended Phase 2A to full 7-TF intraday coverage (was 4 TFs)
- Fixed Pylance type-checking warnings (FrozenSet, Any imports)
- Discussed and documented (not yet implemented): rich regime classification
  system — see "Planned Enhancement: Rich Regime Classification" section above
- Discussed and documented (not yet implemented): ML ensemble / multi-system
  discovery architecture — see new section below

### Next Session

1. Run data.py with the shared-session fix — confirm 1h/2m/1m all reach
   normal success rates (95%+) instead of the 100%-failure pattern
2. If shared session resolves it: re-run analysis.py, expect meaningfully more
   confirmed pairs at 1h (previously 0 due to cascading upstream fetch failures)
3. If shared session does NOT fully resolve it: the fallback diagnostic
   (unconditional WARNING-level empty-result logging) will show the actual
   per-symbol failure text — read those lines before further hypothesizing
4. Once 1h is confirmed working: verify 4h derivation produces valid output
   (BUG-D24 fix should show near-zero freq_invalid count)
5. Confirm 1D aligned universe grew from ~590 to ~1400+ (DataAligner gap-rate
   fix from Session 6, re-verified this session)
6. Dial back the temporary unconditional WARNING-level empty-result logging
   to DEBUG once the shared-session fix is confirmed stable (currently verbose
   by design for diagnosis — see BUG-D31 fix)

---

## Planned Enhancement: ML Ensemble / Multi-System Discovery Architecture

### Concept

Beyond a single meta-labeler, the hypothesis is that the confirmed pair universe
contains multiple distinct behavioral archetypes — e.g., a cluster of pairs that
behave like classic mean-reversion systems (bank pairs: FITB↔FULT, PNC↔FULT) and a
cluster that behaves more like near-arbitrage with little regime dependency
(SPY↔VOO: coint_frac=1.00, H=0.778, structurally different from the bank cluster).

Rather than forcing one global entry/exit model across all pairs, the architecture
should:
1. Discover these archetypes empirically (via `PairCharacteristicsAnalyzer` clustering
   on each pair's characteristic profile — which regimes/features predict its success)
2. Allow different entry/exit logic per archetype, rather than one-size-fits-all rules

### Connection to Existing Planned Architecture

This is not a new module — it's a refinement of how `ml.py` and `analyzer.py` are
designed to work together, consistent with the Lopez de Prado meta-labeling framework
already locked into the methodology:

**The "binary threshold past 80/100" intuition = meta-labeler predicted probability.**
Rather than hand-specifying "if Hurst<0.4 AND regime=high_vol AND z>2: enter" (which
is what the `analyzer.py` decision tree does transparently, per pair), a trained
classifier learns the WEIGHTED combination of all available features (Hurst, regime,
z-score, ADX, spread velocity, macro context, eigenportfolio tier — everything in the
Level 1/2/3 regime feature set documented above) and outputs a single probability.
Entering when that probability crosses a threshold (e.g. 0.80) IS the binary gate the
person described — except learned from data rather than hand-tuned.

**The "discover multiple systems" idea = archetype clustering via PairCharacteristicsAnalyzer.**
Once enough pairs have characteristics cards (decision tree + heatmap per pair, as
designed in the analyzer.py section above), cluster pairs by their characteristic
PROFILE (which features/regimes predict success, not the raw P&L). This reveals
natural families:
- "Mean-reversion archetype": best in low-vol + tight spread + neutral macro,
  regime-sensitive, fails in trending/credit-stress conditions
- "Near-arbitrage archetype": minimal regime dependency, consistently high
  coint_frac, structural relationship (e.g. ETF share-class-equivalents)
- Potentially others not yet hypothesized — let the clustering reveal them rather
  than assuming the taxonomy upfront

Each archetype may warrant a SEPARATE meta-labeler (or separate feature weighting
within one model) rather than forcing one global model to learn all archetypes'
rules simultaneously — analogous to a mixture-of-experts approach.

### Critical Overfitting Risk (must be designed in from the start)

With this many features (leg-level, spread-level, macro, regime — dozens of
candidate features per entry) and a few hundred confirmed pair-trades, there is
real risk that an ML model "discovers" a system that is actually noise rather
than genuine structure. This is the same risk class already identified for
`PairCharacteristicsAnalyzer`'s decision tree, and the SAME discipline applies:

- **CPCV (Combinatorial Purged Cross-Validation)** — already a locked methodological
  decision for backtest.py; applies equally to ml.py's meta-labeler training
- **Chronological hold-out** — train on first 60-70% of trade history per archetype,
  validate on the remainder; a "discovered system" that doesn't hold up out-of-sample
  is not reported as a finding
- **Permutation testing** — shuffle outcomes, refit, compare against the null
  distribution (same technique as analyzer.py's decision tree validation)
- **Minimum N per archetype** — don't split into more archetypes than the data can
  support; a 3rd or 4th cluster with only 15 trades is noise, not a system
- **SHAP analysis** — for the trained meta-labeler(s), SHAP values show WHICH
  features actually drove each prediction; this is the audit trail proving the
  model learned the hypothesized economic structure (e.g. "the model relies heavily
  on yield curve regime for bank pairs but not for SPY↔VOO") rather than spurious
  correlation

### Paper Contribution

This elevates the paper's contribution beyond "we found N cointegrated pairs and
backtested a generic rule": **"we found M distinct behavioral archetypes among
cointegrated pairs, each requiring different conditional entry/exit logic, and built
a regime-aware meta-labeling architecture that adapts to each archetype rather than
applying a uniform global rule."** This is a more sophisticated and more defensible
claim for MFE program review — it demonstrates understanding that statistical
arbitrage is not monolithic, and that na\u00efve global backtesting (the most common
methodological weakness in retail/amateur pairs trading research) is explicitly
being avoided.

### Implementation Sequence (when ml.py is built)

1. Confirmed, stable pair universe with sufficient trade history per pair (prerequisite,
   currently in progress)
2. `PairCharacteristicsAnalyzer` decision trees + heatmaps per confirmed pair (designed,
   not yet built — see earlier section)
3. Archetype clustering on characteristic profiles across all confirmed pairs
4. Per-archetype (or globally-weighted, if clustering doesn't show clean separation)
   meta-labeler training with CPCV + chronological hold-out + permutation testing
5. SHAP analysis confirming learned feature importance matches economic hypothesis
6. Paper exhibit: archetype taxonomy + per-archetype conditional Sharpe + SHAP summary

### Prerequisites

- Confirmed stable pair universe (in progress — blocked on data.py reliability,
  Session 7 work)
- `PairCharacteristicsAnalyzer` built and run on enough pairs to support clustering
  (needs backtest.py trade log — not yet built)
- macro.py FRED data (for the macro-context features feeding the meta-labeler)


---

## Planned Enhancement: Fundamental Valuation Correlation Model

### Concept

The current pipeline establishes that two assets' PRICES are cointegrated
(EG/Johansen) and that their RETURNS are correlated (Pearson/Spearman/
rolling-avg pre-filter). Neither test asks whether the two companies'
underlying VALUATIONS move together — i.e., whether a pair is cointegrated
because the market is pricing both legs off correlated fundamental inputs
(consistent, structural, economically grounded), or whether the price-level
cointegration is a purely statistical/flow-driven artifact not reflected in
how the market is actually valuing the two businesses.

**Core question:** do two price-cointegrated legs also show correlated
valuation dynamics over time — P/E, EV/EBITDA, and DCF-implied fair value —
or does price cointegration sometimes exist WITHOUT fundamental co-movement?
Either answer is a paper finding: confirmed co-movement strengthens the
economic-mechanism argument already made for pairs like ES↔utilities
(Ilmanen framing, Session 4); a confirmed pair with DIVERGING valuation
dynamics is itself a flag — trading on a flow/statistical relationship that
fundamentals don't support is a different, probably lower-conviction risk
profile than one where price and valuation move together.

### Proposed Metrics (per leg, time series — not point-in-time)

- **P/E** — trailing and forward; quarterly cadence (matches earnings
  release frequency, the natural update cadence for fundamental data, unlike
  price data's continuous update)
- **EV/EBITDA** — capital-structure-neutral, more comparable across pairs
  with different leverage than P/E alone
- **DCF-implied fair value** — requires a standardized DCF methodology
  (WACC estimation, terminal growth assumption) applied IDENTICALLY across
  all pair legs for comparability; the most assumption-heavy of the three —
  report with explicit sensitivity to WACC/terminal growth, not as a single
  point estimate

### Methodology Sketch

1. For each confirmed pair (A, B), pull quarterly fundamental data (earnings,
   EBITDA, FCF) for both legs over the full backtest period.
2. Compute the time series of P/E, EV/EBITDA, and DCF-implied value per leg.
3. Correlate the TWO LEGS' valuation-metric time series. Pearson on levels
   is lookahead-biased/spurious for non-stationary ratios the same way
   raw price-level correlation is — use returns/changes in the ratio, or
   test cointegration of the ratio time series itself, mirroring the
   existing EG framework rather than inventing a separate test.
4. Compare: does valuation-dynamics correlation increase, decrease, or track
   price-dynamics correlation/cointegration strength for each confirmed pair?

### Bias Considerations (resolve before implementation, not after)

- **Look-ahead in fundamentals:** reported EPS/EBITDA for a quarter is not
  KNOWN until the earnings release date, not the quarter-end date — must
  align fundamental data to ANNOUNCEMENT date, not period-end date, or this
  introduces exactly the kind of lookahead bias this project's
  bias-first-design principle exists to catch.
- **Survivorship in fundamental data sources:** confirm the fundamental data
  provider's historical coverage doesn't silently exclude delisted/acquired
  names — compounds with the existing current-S&P-1500-only survivorship
  bias rather than introducing a new independent one.
- **DCF assumption sensitivity:** a DCF-implied-value correlation finding
  that only holds under one specific WACC/growth assumption is not a robust
  finding — report the correlation across a small grid of assumptions (e.g.
  WACC ± 1%, terminal growth ± 0.5%), analogous to the Tier 1/Tier 2
  parameter sensitivity already locked in for backtest.py.

### Data Source (not yet selected)

Candidates: yfinance's `.info`/`.quarterly_financials` (free, but historical
fundamental depth and reliability are unverified — same caution as any new
yfinance surface, check via context7 before relying on it), a paid
fundamentals API (FMP, Tiingo, etc.), or SEC EDGAR XBRL directly (free, most
reliable, most implementation effort — would need a structured extraction
layer). Decision deferred; do not build against yfinance's fundamentals
endpoints without first confirming historical depth covers the full backtest
period for at least the current confirmed-pair universe.

### Status

Idea stage — not yet scoped into a build session. Lower priority than
ml.py/backtest.py (the core predictive/performance claims), and explicitly
gated on having a stable confirmed-pair universe with real trade history
first, same prerequisite as analyzer.py and the regime-classification
enhancement.

---

## Session 7 Continued — sp600/sp400 Wikipedia Scraper Saga (Full Account)

### The Full Diagnostic Journey (documented to prevent re-investigation)

This was the longest single debugging thread of Session 7, spanning multiple
wrong hypotheses before reaching ground truth. Documented in full because the
journey itself contains the lesson, not just the conclusion.

**Symptom:** `S&P SmallCap 600: fetched 0 tickers` and a correspondingly
collapsed universe (536 assets instead of ~1500+), recurring across many runs.

**Hypothesis 1 (wrong):** Generic bot-identifying User-Agent string
(`"CAMARF/1.0"`) was being blocked by Wikipedia. Fixed by switching to a
realistic Chrome User-Agent across all Wikipedia-facing requests (sp400,
sp600, Nasdaq-100, BRK holdings, iShares CSV). This fix was real and correct
but did NOT resolve the sp600 issue — proving the User-Agent was A bug, not
THE bug blocking sp600 specifically.

**Hypothesis 2 (wrong, briefly held):** Stale/mismatched local file —
diagnosed via the exact same symptom pattern that had explained earlier
yfinance issues (old code persisting despite "fixes"). Ruled out via direct
MD5 checksum verification — the file genuinely matched what was provided,
and a targeted grep confirmed only one definition of each relevant function
existed (no duplicate/shadowing).

**Hypothesis 3 (wrong):** Logic bug in `_fetch_sp_index_wikipedia`'s
column-matching — specifically, that the function might be finding a
secondary "recent changes" history table before the main 600+ row
constituent table, with a flawed best-candidate selection.

**Resolution method:** rather than add a fourth layer of speculative fix,
built a fully isolated standalone test script (`test_sp600_isolated.py`)
that mirrors the production scraper logic exactly, run completely outside
data.py. This succeeded immediately: HTTP 200, 16 tables found, table[3]
correctly identified with 579/603 valid tickers — comfortably above the
500-ticker threshold.

**Conclusion:** the scraping logic itself was correct all along. The
intermittent "0 tickers" failures are genuine transient Wikipedia/network
flakiness — the same exact code succeeds on some invocations and fails on
others, with no reproducible code-level cause found despite three rounds
of hypothesis-driven fixes. This matches the broader pattern seen with
yfinance throughout the day (DNS errors, intermittent timeouts) — likely
related to sustained heavy request volume against free-tier endpoints
over many hours of iterative debugging.

**Practical resolution (not a root-cause fix, a mitigation):**
1. `seed_sp_caches.py` — standalone script with retry logic (5 attempts,
   8s delay between), run manually/periodically to populate
   `output/cache/sp400.json` and `output/cache/sp600.json` independent of
   the main data.py run.
2. Fixed a genuine bug found along the way: `_fetch_constituents_cached`
   was unconditionally caching whatever the live fetch returned, INCLUDING
   empty results — meaning a single transient failure during a `data.py`
   run would silently overwrite a perfectly good previously-seeded cache
   with an empty `[]`. Fixed to only persist non-empty results; an empty
   live-fetch result is simply returned without touching the cache file.

### Key Methodological Lesson From This Saga

When a third-party tool (DeepSeek, or any other LLM) is used to summarize
raw log/script output before sharing it for diagnosis, treat that summary
as a hypothesis, not ground truth. During this investigation, a summary was
shared claiming the scraper "found table[3] with 579 tickers, met the
threshold, but still failed after 5 retry attempts and gave up" — this is
a logical impossibility given the actual retry script's structure (meeting
the threshold causes an immediate return; there is no code path where both
things are true). The summarizing tool had apparently conflated two
different indices' results (MidCap 400's genuine failure and SmallCap 600's
genuine success) into one garbled description, and was speculating about
a "Python traceback" it likely never actually saw.

**Rule going forward:** when a summary contains something that doesn't add
up logically against the actual code's structure, ask for the literal raw
text directly, not a re-summary. This resolved the contradiction
immediately once requested.

---

## Claude Code Integration — Framework for Working With Claude on This Project

### Why This Section Exists

A significant fraction of Session 5-7's time cost was pure file-transfer
and verification overhead inherent to working through claude.ai's chat
interface: generating a fix, copying it to outputs, the user downloading
and replacing a local file, MD5 checksum verification to confirm the
replace actually happened, and round-trips of "run this isolated test
script and paste the output back" for things that could have been directly
observed in a live terminal. None of this overhead is fundamental to the
debugging difficulty — it's a consequence of the chat interface lacking
direct filesystem/terminal access to the user's actual environment.

**Decision: set up Claude Code for this project**, using `CLAUDE.md` (new
file, project root) as the persistent context bridge. Claude Code uses the
same underlying model — the reasoning depth and verification discipline
that characterized this conversation are properties of the model given
good context, not something unique to this specific chat thread's hidden
state. `DEVELOPMENT.md` (this file) plus `CLAUDE.md` are the mechanism for
that context to transfer to any new session, on any surface.

### What CLAUDE.md Contains (see actual file for full content)

- Project thesis and architecture (condensed from this document)
- Non-negotiable architecture rules (data.py/analysis.py separation,
  yfinance-primary, GapFlag system, no-bandaid-fixes)
- A "known-resolved issues, do not re-suggest" list — the yfinance
  curl_cffi session bug, the period-string-keyed-by-wrong-variable bug,
  the 8h removal, the 4h session-alignment requirement, the sp400/600
  scraper flakiness conclusion — anything a fresh session might otherwise
  waste time re-discovering
- A "working style" section capturing the collaboration patterns that
  have proven effective: full comprehension before code, one best fix not
  multiple options, verify with a reproducing test before claiming done,
  stop and ask for raw evidence after ~3 failed fix attempts rather than
  guessing a 4th time, distrust third-party log summaries when they don't
  logically add up
- Recommended plugin list with concrete trigger conditions

### Plugin Decisions (Session 7)

Researched and verified (not assumed) before recommending:

- **`context7`** (installed) — live documentation lookup. Concrete trigger:
  before writing/debugging code against yfinance, ib_insync, statsmodels,
  or scikit-learn, where training-data knowledge may be stale relative to
  the installed version's actual behavior. Directly motivated by the
  curl_cffi session surprise — a context7 lookup would likely have
  surfaced that requirement immediately instead of requiring empirical
  discovery through repeated failures.

- **`feature-dev`** (confirmed official, bundled with Claude Code itself —
  `anthropics/claude-code` repo) — guided feature development workflow
  with three specialist agents (code-explorer, code-architect,
  code-reviewer). Recommended specifically for the upcoming `ml.py`,
  `backtest.py`, `analyzer.py`, `macro.py` builds, which are genuine new
  feature development rather than the bug-fixing that has dominated
  Sessions 5-7.

- **`claude-md-management`** (confirmed from the official, Anthropic-
  managed `anthropics/claude-plugins-official` marketplace) — keeps
  CLAUDE.md from drifting into an unmaintained mess as the project's
  context needs grow.

- **`skill-creator`** (confirmed official) — available if a CAMARF-specific
  recurring workflow emerges that's worth packaging as a custom skill
  (e.g. "diagnose a data.py run from its log file" as a standing,
  reusable skill rather than ad-hoc each time).

- **`ponytail`** (real, verified, explicitly NOT recommended) — a popular
  (40k+ star) plugin whose entire philosophy is minimizing code written,
  flagging "over-engineering." This directly conflicts with this
  project's established discipline of thorough verification, explicit
  diagnostic instrumentation, and no-bandaid-fixes. Documented here so a
  future session doesn't install it on the assumption that a popular
  plugin is automatically a good fit.

- **`draw.io`** (real, verified, third-party plugin by `little-hands`) —
  genuinely useful for visualizing the data.py/analysis.py architecture
  and decision trees (e.g. the yfinance/IBKR fallback logic) as actual
  diagrams. Noted for use near v1 shipment, not a current priority while
  still in active data-pipeline debugging.

- **Investigated and found NOT to be Claude Code plugins at all:**
  `Handy` (github.com/cjpais/handy) is an unrelated standalone speech-to-
  text desktop application (Whisper/Parakeet-based, Rust+Tauri) — no
  integration with Claude or this codebase, though could be used
  separately for voice-dictating messages during long sessions.
  `SkillSpector` (github.com/nvidia/skillspector) IS relevant but in a
  different way than initially assumed — it's a security SCANNER for
  Claude Code skills/plugins (64 vulnerability patterns, research-backed
  finding that 26.1% of scanned skills had at least one vulnerability and
  5.2% showed likely malicious intent). Recommended practice: scan any
  new third-party plugin with SkillSpector before installing, going
  forward — not just for this project, as general practice.

### What Does NOT Automatically Transfer to a Fresh Claude Code Session

Being explicit about this rather than overselling continuity: the specific
turn-by-turn memory of this conversation — which exact hypotheses were
tried and ruled out in which order, the precise wording of every fix — does
not transfer automatically. That is exactly what the "Known-Resolved
Issues" list in CLAUDE.md and the full bug registries in this document are
FOR. They are not a backup of memory; they are the actual mechanism by
which a fresh session reconstructs equivalent understanding. Keeping both
files current after every substantive session is not optional bookkeeping
— it is the continuity system.

---

## Session 7 — Final Log Entry

2026-06-19 through 2026-06-20:
- Diagnosed and fixed BUG-D24 through BUG-D31 (see earlier Session 7
  bug registry section): 4h derivation diagnostics, Phase 2A full TF
  coverage, 2m/3m period-string bug, yf.download→Ticker().history()
  revert, defensive period validation, pytz dependency, the yfinance
  shared-session false lead and correction (curl_cffi requirement)
- Fixed BUG-D32: 4h resample using clock-aligned bins instead of
  session-aligned (origin="start_day", offset="9h30min"); frequency
  validation now filters structural overnight/weekend gaps before
  computing the validation median
- Investigated and resolved (via isolated testing, not further code
  guessing) the S&P 400/600 Wikipedia scraper saga — concluded genuine
  intermittent network flakiness, not a code bug; built
  seed_sp_caches.py with retry logic as practical mitigation
- Fixed BUG-D33: _fetch_constituents_cached was unconditionally caching
  empty live-fetch results, overwriting good seeded caches on any
  subsequent transient failure — fixed to never persist empty results
- Added universe-size sanity guard (loud banner if < 1000 assets)
- Researched and verified (not assumed) a set of Claude Code plugins:
  context7, feature-dev, claude-md-management, skill-creator (recommend),
  ponytail (verified real, explicitly do not recommend — philosophy
  conflict), draw.io (verified real, note for later), Handy (verified —
  unrelated speech-to-text app, not a Claude plugin), SkillSpector
  (verified — security scanner for AI agent skills, recommend running
  against any new third-party plugin before install)
- Created CLAUDE.md as the persistent Claude Code context file
- Decided to set up Claude Code for this project going forward, with
  CLAUDE.md + DEVELOPMENT.md as the continuity mechanism between sessions
  and across surfaces (claude.ai chat vs Claude Code)

### Next Session

1. Confirm `seed_sp_caches.py`'s retry logic successfully populates both
   sp400.json and sp600.json (check for SAVED vs GAVE UP in its output)
2. Run data.py — confirm universe size reaches ~1500 (no more `!!!`
   abnormal-size banner)
3. Verify the 4h session-alignment fix (BUG-D32) produces near-zero
   freq_invalid count in the next run's latest_run_data.log
4. Run analysis.py — check for new confirmed pairs at 1h, 4h, 1D now
   that data quality issues are resolved at those TFs
5. Set up Claude Code: install, point at the CAMARF repo, verify
   CLAUDE.md is being read at session start, install context7 +
   feature-dev + claude-md-management + skill-creator
6. Once data.py/analysis.py are stable: begin macro.py (FRED integration)
   as a relatively self-contained build, good candidate for testing the
   feature-dev workflow
7. Then: PairCharacteristicsAnalyzer (designed, not built) once enough
   confirmed pairs exist with stable characteristics

---

## Session 8 — Claude Code First Real Session: data.py/analysis.py Verified End-to-End

### Context

First session actually running Claude Code on this project (Session 7 set it
up but didn't yet use it for a full run). The request was a straightforward
diagnosis ("figure out why data.py isn't working") plus explicit permission
to act autonomously overnight. What followed was not a single fix — it was
six distinct, previously-undiscovered bugs, several of which directly
contradicted what this very document claimed was already fixed. The
methodological lesson of this session: **"documented as fixed" is a claim
to verify against the running code, not a fact to build on** — see the new
"Development Process & AI Tool Disclosure" section above for the two
concrete examples (BUG-D31, BUG-D32) that motivated this.

### Session 8 Bug Registry

**BUG-D34 (root cause of the universe collapsing to 86 assets): `pd.read_html(resp.text)` no longer accepts literal HTML strings on pandas 2.2.3/3.0.3**
Root cause: pandas hands a raw string `io` argument to lxml's `etree.parse()`,
which always treats a string as a filename/URL, never as literal content —
not a network/Wikipedia flakiness issue as Session 7's CLAUDE.md entry
concluded. 100% reproducible, not intermittent. Affected all 5
`pd.read_html()` call sites in `data.py` (S&P 500/400/600, Nasdaq-100,
Russell 2000, BRK holdings) plus `seed_sp_caches.py`. S&P 500 survived via
its stale-cache fallback; S&P 400/600 had no fallback cache, so they
returned 0 tickers, collapsing the universe.
Fix: wrap every `resp.text` in `io.StringIO()` before passing to
`pd.read_html()`. Verified live against the real Wikipedia pages (607/603
ticker candidates parsed correctly) before declaring fixed.

**BUG-D35: `seed_sp_caches.py` (and transitively `data.py`'s cache) picked Wikipedia's historical "Selected changes" table instead of current constituents for S&P 400**
Root cause: the "pick whichever column has the most matching tickers"
heuristic preferred a MultiIndex column `('Added', 'Ticker')` — the
"Selected changes to the list" table, which lists every ticker ever added
to the index over its full history (607 entries, full of names delisted/
acquired 8-15 years ago: JDSU, APOL, CBST, HSH, ANR, LXK, WWAV...) — over
the real current-constituents table (400 entries, flat `'Symbol'` column),
purely because 607 > 400. `data.py`'s OWN live-fetch table-selection logic
was already correct (verified directly: returns clean 400 tickers); the bad
data came entirely from a cache file `seed_sp_caches.py` had written
earlier in the session with the wrong table, which `data.py`'s 24h
freshness check then trusted over its own (correct) live fetch.
Fix: skip MultiIndex columns entirely in `seed_sp_caches.py`'s
`fetch_index()` — the real constituents table always has flat string
column names. Verified: 400/603 clean tickers, zero historical zombies.

**BUG-D36: `MIN_BARS_REQUIRED['1m']`/`['3m']` were mathematically impossible to satisfy**
Root cause: `config.py`'s comments ("~35 days * 390 bars/day") predate the
Yahoo 8-day hard limit on 1m-granularity data. `_YF_INTRADAY_MAP` correctly
fetches 1m at `period="5d"` (~1950 bars max) and derives 3m from that same
5-day source (~650 bars max) — but the thresholds (5000, 3000) assumed a
35-day source that was never actually used. Every single 1m/3m fetch,
regardless of data quality, failed `DataCleaner.clean()`'s min_bars check
silently — 100% guaranteed failure, forever, for both timeframes.
Fix: `1m` → 1500, `3m` → 500 (~80% of the real achievable max, matching the
fill-rate ratio already used for `2m`). Verified: AAPL now returns
1950/650 bars respectively, clearing the new thresholds.

**BUG-D37 (contradicts this document's own BUG-D32 entry — that fix was never actually applied): 4h resample used clock-aligned bins, not session-aligned**
Root cause: `YFinanceFeed._resample()` called `df.resample("4h")` with no
`origin`/`offset`, defaulting to clock-aligned bins (00:00/04:00/08:00/
12:00/16:00/20:00). For a 9:30-16:00 NYSE session this puts real bars in
the 08:00 and 12:00 buckets — wrong timestamps, and the resulting ~20h
median gap (one bucket capturing only 2.5h of session, the other 4h)
would corrupt any time-of-day/session-based downstream analysis. Verified
directly: a real fetch produced bars stamped 08:00/12:00, not 09:30/13:30,
despite Development.md claiming this was fixed in Session 7.
Fix: `origin="start_day", offset="9h30min"` on the 4h resample specifically
(left the 3m resample untouched — no evidence it was misaligned). Verified:
bars now correctly stamped 09:30/13:30, exactly 14400s apart within a day.

**BUG-D38: stale per-ticker `yf_period_<SYMBOL>_<interval>` cache entries with no expiry, silently capping ~80 tickers' 1h fetches forever**
Root cause: `get_intraday_fallback()` caches whichever period string
"worked" per ticker+interval in a meta parquet file, with no age limit and
no re-validation against current `MIN_BARS_REQUIRED`. ~81 of 1510 cached
1h entries held a stale `"60d"` override (from some earlier, since-changed
default) instead of the correct `"730d"` — `60d` at 1h only yields ~420
bars, below the 500-bar minimum, so `DataCleaner.clean()` silently rejected
the result with the reason never logged anywhere in the call chain. Because
no valid data ever got saved, these tickers stayed flagged "needs fetch"
and failed identically every run, forever — explains why a sample of
"needs fetch" tickers showed ~98% failure while a fresh random sample of
the same universe succeeded at ~94%+.
Fix: deleted all 3,254 `yf_period_*` cache files; they regenerate cleanly
under the now-corrected `MIN_BARS_REQUIRED` thresholds.

**BUG-D39 (the most severe finding this session — direct violation of the project's Non-Negotiable Architecture Rule #1): `analysis.py` was never actually read-only**
Root cause: `UniverseBuilder.build()`'s `connect` parameter only ever chose
the intraday-fetch SOURCE (IBKR vs. yfinance) — it never gated WHETHER
fetching happened. `connect=False` literally means "if anything needs
intraday data, fetch it via yfinance instead of IBKR," not "never fetch."
Phase 1's daily yfinance fetch ALSO runs unconditionally whenever cache is
stale, regardless of `connect`. `analysis.py` calling `build(connect=False)`
— believing this satisfied "analysis.py must never touch IBKR or
yfinance" — had been silently running the full Phase 2A yfinance intraday
sweep every single time it ran. Caught live: watching a real `analysis.py`
run log "Phase 2A: yfinance intraday sweep (primary pipeline)", which
should be structurally impossible for analysis.py to print.
Fix: added a genuine `fetch: bool = True` parameter to `build()`. When
`False`, both Phase 1's daily-fetch trigger and Phase 2's `ibkr_work` list
are forced empty before their existing (untouched) logic runs — a
surgical guard rather than a rewrite of either multi-hundred-line block.
`analysis.py` now calls `build(connect=False, fetch=False)`. Verified via
a direct read-only `build()` call (logs "Read-only mode (fetch=False):
... using cache as-is" at both phases, no Phase 2A line) and confirmed
identically in a live `analysis.py` run afterward.

**BUG-A13 (bias-relevant): `build_returns_matrix()` imported `_gap_aware_returns` but never called it**
Root cause: the function computed log returns directly off raw `df["close"]`
values with zero GapFlag masking, contradicting CLAUDE.md's "never silently
forward-fill a DATA_GAP bar into a correlation calculation" rule. A bar
forward-filled across a >5-bar gap produces one artificially large return
when the real price resumes, which fed directly into the Pearson/Spearman/
rolling-avg correlation pre-filter undetected.
Fix: replaced the raw close-diff computation with per-asset
`_gap_aware_returns(df)` calls before padding/stacking into the returns
matrix. Verified with a synthetic DATA_GAP bar (artificial +80%/-40% jump):
both the gap bar's own return and the adjacent transition return correctly
become NaN instead of contaminating the matrix.

**BUG-D40: cache-contamination frequency checks computed the median bar-gap including overnight/weekend gaps, silently deleting/rejecting good 4h files on every single `build()` call**
Root cause: both `_clean_contaminated_cache()` (runs unconditionally at the
start of every `build()`, in data.py AND analysis.py) and
`DataStore.validate_frequency()` computed `diffs.median()` over the WHOLE
file. A correctly session-aligned 4h file has exactly 2 bars/day, so HALF
its gaps are the legitimate ~20h overnight break — including them pushes
the median right up near (often past) the contamination threshold. This
silently destroyed BUG-D37's fix on every subsequent run: confirmed live,
1500+ valid 4h files written by `data.py`, only 7 left by the time
`analysis.py` read the cache moments later, with zero error or warning
logged (the deletion itself logs only at DEBUG level). This is the THIRD
distinct place this session where Development.md's BUG-D32 "filter
structural gaps before computing the median" fix was claimed-done but
absent from the actual code.
Fix: both functions now exclude gaps >8h before computing the median
(falling back to the unfiltered median when fewer than 3 intraday-scale
gaps exist, so 1D/7D/1M/etc. — which have no "intraday" component at all —
are unaffected). Verified: a real 4h file now survives repeated
`_clean_contaminated_cache()` calls; a full `analysis.py` run confirmed
1507 aligned 4h assets (not 7) and produced 1 confirmed pair.

**BUG-D41 (Session 8 continuation, 2026-06-21 morning, not a current code bug — cache hygiene): stale `30m` cache from an older pipeline version, missing the entire morning session**
Symptom: `30m` correlation matrices observed showing single-digit
asset counts. Root cause: every cached `_30min.parquet` file (1511 of
them) had only 5 of the expected 13 daily bars — 13:30-15:30 ET only,
missing 09:30-13:00 entirely, for every single trading day in every single
file. Confirmed via direct testing that a FRESH fetch with TODAY's code
(`get_intraday_fallback`, `snap_timestamps`, raw yfinance call) correctly
returns all 13 bars/day — this was leftover data from some earlier, no-
longer-present bug, not an active defect.
Fix: `DataStore.clear_tf_cache("30m")` (existing utility, not a new one) to
delete all 1511 stale files, then a normal `data.py` run to refetch.
1510/1514 succeeded; verified full 13-bars/day on a fresh random sample.
`analysis.py --timeframes 30m` backfilled the corrected result (0 confirmed
pairs survive FDR on the complete data — a legitimate finding, not an
artifact).

**BUG-A14 (found and fixed same session, 2026-06-21 afternoon): `output/results/3m/` and `output/results/3M/` collide on Windows**
Root cause: `_output_dir(tf_label)` joined `tf_label` directly into the
results path. NTFS is case-insensitive, so "3m" (3-minute) and "3M"
(3-month) — and, not initially noticed, "1m"/"1M" (1-minute/1-month) —
resolved to the same physical directory. No data was lost before the fix
(3M/1M consistently found 0 significant pairs every run, so they never
reached the write step that would have overwritten 3m/1m's results), but
the risk was live: whichever timeframe processed second would have
silently overwritten the other's `pairs.parquet` the first time both
produced confirmed pairs in the same run.
Fix: `_output_dir()` now maps `tf_label` through `DataStore._TF_SAFE`
(`output/results/3min`, `output/results/3mo`, etc.) — the SAME
case-distinct naming convention already used for cache filenames, not a
new one invented for this. Existing live result directories were renamed
in place (not regenerated) to avoid an unnecessary full re-run; a
subsequent full clean `analysis.py` run (the one that also re-verified
Session 8's other fixes a fourth time, see "Final Verified State" above)
confirmed the new naming takes effect correctly and produced a
byte-for-byte identical 11-pair result and 15-symbol manifest — confirming
the rename was purely cosmetic, not a methodology change.

### Other Findings (flagged, not yet fixed)

- **Final pipeline summary table is misleading.** The printed per-TF
  `pairs=N` count in `analysis.py`'s end-of-run summary is the pre-
  `coint_fraction_rolling≥0.70`-filter EG/FDR-survivor count, not what
  actually gets saved to `pairs.parquet` / the confirmed-pairs manifest.
  E.g. printed `3m: pairs=15` vs. 7 actually saved; `1h: pairs=2` vs. 1
  actually saved. The SAVED data and manifest are correct (the episodic-
  cointegration defense is doing its job); only the human-facing summary
  overstates the count. Worth fixing the print statement, not urgent.
- **`UA/UAA`-style malformed tickers**: a small number of Wikipedia table
  cells list dual share classes in one cell (e.g. Under Armour). Not
  investigated further — low volume, absorbed fine by the existing
  exclusion-list/retry architecture.
- Dead `"8h"` references remain in a few generic IBKR duration tables and
  one `MIN_BARS_REQUIRED` entry in `config.py` — functionally inert
  (nothing calls them with `tf_label="8h"`), cosmetic cleanup only.

### Final Verified State (full clean `analysis.py` run, 87.0 min, 2026-06-21)

| TF | EG/FDR survivors (printed) | Actually saved (post coint_frac filter) | Trios | Cross-asset | Regimes |
|----|------|------|------|------|------|
| 1m | 1 | 0 | 0 | 0 | 2 |
| 2m | 0 | 0 | 0 | 0 | 0 |
| 3m | 15 | **7** | 1 | 1 | 11 |
| 5m | 1 | 0 | 0 | 0 | 2 |
| 15m | 3 | **3** | 1 | 0 | 5 |
| 30m | 0 | 0 | 0 | 0 | 0 |
| 1h | 2 | **1** | 0 | 0 | 4 |
| 4h | 1 | 0 | 0 | 0 | 2 |
| 8h | — | 0 | 0 | 0 | 0 |
| 1D | 0 | 0 | 0 | 0 | 0 |
| 7D | 1 | 0 | 0 | 0 | 2 |
| 1M | 0 | 0 | 0 | 0 | 0 |
| 3M | 0 | 0 | 0 | 0 | 0 |
| 6M | 0 | 0 | 0 | 0 | 0 |

11 validated confirmed pairs across 3 timeframes (3m, 15m, 1h), 2 trios,
1 cross-asset pair. `confirmed_pairs_manifest.json`: 15 symbols. Result
reproduced identically five separate times: the original full run, a
targeted `--timeframes 4h` backfill, a targeted `--timeframes 30m`
backfill, a completely fresh full re-run from scratch, and a second fresh
full re-run after the BUG-A14 directory-rename fix (below) — same 11
pairs, same 15-symbol manifest, every time. That five-for-five
reproducibility, not the absence of a crash, is the actual basis for
calling this "verified."

`data_ibkr.py` run against the live IB Gateway (127.0.0.1:4001): 15/15
symbols, 105/105 TF-fetches (7 TFs × 15 symbols) saved, 0 failed, clean
connect/disconnect.

### Why 1D/1M/3M/6M Show Near-Zero Confirmed Pairs (Investigated, Not a Bug)

Question raised on seeing the table above: with a ~1500-asset universe,
shouldn't there be more daily/monthly pairs? Investigated directly rather
than assumed away — confirmed it's a real methodological property of the
full-sample EG screen at long horizons, not a data or code defect.

**Raw (pre-FDR) significance rates by TF, full pipeline run:**

| TF | tested | raw p<0.05 | raw rate | vs. ~5% expected under H₀ |
|----|--------|-----------|----------|---------------------------|
| 15m | 14,412 | 585 | 4.06% | close to chance — consistent with real signal |
| 1h | 65,721 | 2,335 | 3.55% | close to chance — consistent with real signal |
| 1D | 122,082 | 2 | 0.0016% | ~3,000x *below* chance |
| 1M | 34,263 | 9 | 0.026% | ~190x below chance |

A raw rate far *below* the chance rate isn't noise — it means the test
itself is unusually strict at these TFs, not that the universe lacks
relationships.

**Direct evidence (EG on full price history vs. just the last 5 years, several pairs including this project's own established confirmed pairs):**

| Pair | Full-sample EG p | Last-5y EG p | Full-sample n (days) |
|------|------------------|--------------|----------------------|
| XOM/CVX | 0.436 | 0.408 | 14,546 (since 1968) |
| JPM/BAC | 0.911 | 0.753 | 11,571 (since 1980) |
| KO/PEP | 0.114 | 0.916 | 13,423 (since 1973) |
| **NTRS/STT** | **0.000** | 0.345 | 10,939 (since 1983) |
| **SHW/UNP** | **0.004** | 0.265 | 11,548 (since 1980) |

NTRS↔STT and SHW↔UNP — the project's own headline confirmed pairs from
earlier (intraday) sessions — show strong full-sample cointegration but NO
significant cointegration in just the last 5 years. The full-sample EG
screen at 1D is testing whether two price levels stayed cointegrated across
40-60+ years of M&A, business-model change, and sector rotation — a
genuinely demanding bar, and one that current relationships can fail while
still showing up as "confirmed" if the test only looks at the full sample.

**Why this is a real limitation, not just an explanation:** `coint_fraction_rolling`
(the existing episodic-cointegration defense, Session 6) is a SECONDARY
filter applied only to pairs that already pass the PRIMARY full-sample EG
screen. At 1D/1M/3M/6M, the primary screen is so strict that almost nothing
ever reaches the secondary filter in the first place — `coint_fraction_rolling`
can't rescue a pair that the full-sample test never let through. The two
defenses operate at the wrong stage for this specific failure mode at long
horizons.

**Secondary, independently-predicted factor:** Ilmanen's term structure of
mean reversion (Session 3 Additions, "Term structure of mean reversion")
predicts momentum — not mean reversion — dominates at 1-12 month horizons,
with mean reversion only returning at multi-year horizons. So 1M/3M/6M
showing near-zero pairs is independently expected from the economics
literature already cited in this document, separate from the full-sample-
window issue above.

**Confirmed as a planned point of comparison (not yet implemented):** run
EG (and `coint_fraction_rolling`) twice per pair at 1D/1M/3M/6M — once on
the full sample (current behavior) and once on a bounded recent lookback
(e.g. 5-10 years) used as its own PRIMARY screen, not just as a secondary
diagnostic gating pairs that already survived a 40-60 year full-sample
test. Report both Gold/Silver/Bronze tier assignments side by side per
pair. This directly tests "is this pair cointegrated now" — the actually
decision-relevant question for a tradeable strategy — against "has this
pair ever, on average, been cointegrated across its entire trading
history," and the GAP between the two screens at long-horizon TFs becomes
its own paper exhibit (same fragile-vs-robust comparison logic as the
portfolio construction table above, applied to the cointegration test
itself rather than to position sizing). Cross-reference: "Cointegration
Hierarchy" under Methodological Decisions Locked, near the top of this
document — add the bounded-window screen there as a fourth tier dimension
once implemented, alongside EG/KPSS/PO.

### Also This Session (infrastructure, not CAMARF methodology)

- Recovered a corrupted local git repository (missing/broken objects,
  missing `.git/index`) — almost certainly OneDrive interfering with `.git`
  internals, not anything in this session's own actions. Repaired
  non-destructively (recovered objects from the GitHub remote, rebuilt the
  index from HEAD via `git reset`) without touching any working-tree file.
  Flagged as an ongoing environmental risk: this is a OneDrive-synced
  folder, and `.git/` plus the run-log files vanished unprompted more than
  once in one session.
- Added a scoped Claude Code permission allowlist (read-only commands only;
  declined a blanket "skip all permissions" request pending explicit
  confirmation, consistent with this project's stated caution around
  unattended execution).

### Next Session

**Confirmed 2026-06-21 (later same session):** `analysis.py` re-verified a
fourth time after the `3m`/`3M` path-collision fix (see item 2, now
resolved) with a full clean run — identical 11-pair result, directory
structure now correctly `1min`/`3min`/`1hr`/`4hr`/`5min`/`15min`/`7day`
(collision-free). `confirmed_pairs_manifest.json` came out byte-for-byte
the same 15 symbols as before the fix, confirming the rename was purely
cosmetic and `data_ibkr.py`'s prior run (105/105 fetches, 0 failed) remains
valid — no re-fetch needed.

**Build order locked in: `macro.py` → `ml.py` (not `ml.py` first).**
Rationale: macro context (yield curve, credit spread, VIX regime, NBER
recession flag) is already specified as a Level 3 feature in the "Rich
Regime Classification" enhancement above, feeding the SAME meta-labeler
`ml.py` is designed around — building `macro.py` first means `ml.py`'s
first version ships with its full intended feature set instead of being
built narrow and retrofitted later (which would mean re-running SHAP/
ablation analysis a second time). `macro.py` is also small and
self-contained (~1 day estimate, already noted as a good `feature-dev`
test case). The macro/spread correlation question doesn't need a separate
analysis step — it falls out of `ml.py`'s already-planned SHAP feature
importance and ablation analysis (full model vs. full-minus-regime OOS
Sharpe) once both exist.

1. ~~Decide macro.py vs. ml.py first~~ — resolved above.
2. ~~Fix the `3m`/`3M` Windows path collision~~ — resolved, verified above.
3. Fix the misleading pipeline-summary print (pre-filter vs. saved counts).
4. Re-run `seed_sp_caches.py` periodically (weekly, per its own docstring)
   now that it's fixed — and consider whether `data.py`'s own live
   `_fetch_sp_index_wikipedia` should be the ONLY source of truth, given it
   was already correct all along and the seed script was the one with the
   bug.
5. Build the fragile-to-robust portfolio comparison table (tangency / min-
   variance / min-CVaR / independent RP / true RP / HRP / constrained
   optimizer) as a `backtest.py` exhibit once `backtest.py` exists — see
   expanded "Portfolio Construction" section above.
6. Consider scoping the fundamental valuation correlation model (P/E,
   EV/EBITDA, DCF-implied value) — see "Planned Enhancement" section above.
   Idea stage only; not prioritized over macro.py/ml.py.
7. Implement the bounded-recent-window EG/`coint_fraction_rolling` screen
   at 1D/1M/3M/6M as a point of comparison against the full-sample screen —
   see "Why 1D/1M/3M/6M Show Near-Zero Confirmed Pairs" above.
8. Prioritize the portfolio-level VaR + historical-crash stress-test work
   (Category 1: 2008 GFC, 2020 COVID, 2022 rate shock, 2023 regional bank
   stress) alongside core performance metrics when `backtest.py` is built —
   not after, as a nice-to-have. See "Stress Testing Framework" priority
   note above.

