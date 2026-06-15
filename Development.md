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

Three approaches:
1. **Mean-variance efficient frontier** — maximize Sharpe given the covariance matrix of pair P&L streams. Requires at least 2× the number of pairs in observations for stable covariance estimates.
2. **Maximum diversification** — minimize average pairwise correlation between positions. Naturally downweights clusters of similar pairs.
3. **Equal-weight baseline** — all confirmed pairs equally weighted. The paper reports whether MV or max-div beats equal-weight OOS; this is often not the case (parameter estimation error in the covariance matrix), and reporting the failure honestly is rigorous.

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