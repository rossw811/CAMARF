# CAMARF — Session Handoff Summary
**Date:** 2026-06-13  
**Current phase:** data.py complete → analysis.py ready to build  
**Repository:** github.com/rossw811/CAMARF  
**Author:** Ross W. — Washington State University (targeting transfer Fall 2027)

---

## Project in One Paragraph

CAMARF (Cross-Asset Co-Movement Arbitrage Research Framework) is an institutional-grade quantitative research framework for a transfer application portfolio targeting USC Marshall, UW CFRM, CMU Tepper, Cornell Dyson, UIUC Gies, Georgetown, UT Austin, and MFE programs at Baruch/Berkeley/Columbia. The core thesis: cross-asset co-movement relationships exhibit regime-dependent, volatility-normalized arbitrage structure predictable at statistically significant rates using multiclass ML, with predictability degrading systematically across timeframes, regimes, and asset class boundaries. It is a research paper + working codebase, not just a backtest.

---

## Repository Structure

```
CAMARF/
├── config.py          ✅ Complete
├── data.py            ✅ Complete
├── analysis.py        🔄 NEXT — ready to build
├── ml.py              ⏳ Planned
├── backtest.py        ⏳ Planned
├── options.py         ⏳ Planned
├── stats.py           ⏳ Planned
├── report.py          ⏳ Planned
├── README.md          ✅ Complete
└── DEVELOPMENT.md     ✅ Complete — full technical reference
```

---

## data.py — Final State

**Status:** Production-ready. Do not modify without specific reason.

**Final pipeline results:**
```
529 assets passed  |  1 excluded (FDXF — no yfinance daily data)
6,233 symbol-timeframe combinations
5,468 loaded from Parquet cache  |  765 fetched this session
Coverage: 98.2% of theoretical maximum (529 × 12 TFs)
```

**Data source architecture:**

| Asset Class | Daily/Weekly/Monthly | Intraday |
|---|---|---|
| S&P 500 Equities (503) | yfinance bulk | yfinance fallback (IBKR unavailable on paper) |
| Crypto (5) | yfinance (BTC-USD format) | yfinance fallback |
| Forex (10) | yfinance (EURUSD=X format) | yfinance fallback |
| Commodities (8) | IBKR | IBKR working for 4h/8h |
| Futures (6) | IBKR | IBKR working for 4h/8h |

**Key confirmed findings about IBKR paper account:**
- 4h, 8h, 1h equity bars: 100% unavailable — subscription limitation
- Commodities/futures 4h/8h: working (GC=1898 bars, ZC=2956 bars, NQ=1133 bars)
- 1m data: largely unavailable from both IBKR and yfinance (8-day Yahoo hard limit)
- VLTO: permanently unavailable from all sources

**Critical classes:**
- `DataStore` — Parquet cache, permanent storage
- `ProgressLogger` — crash-safe resume with config-hash invalidation; writes to TEMP on OneDrive lock
- `DataAligner` — NYSE calendar alignment, forward-fill gaps, `is_gap: bool` column
- `DataCleaner` — standardize→deduplicate→gap-fill→roll-adjust→liquidity filter→min-bar validate; retains `vwap` field from IBKR `average`; `source` field on QualityReport ("ibkr"/"yfinance"/"yfinance_resampled")
- `YFinanceFeed` — bulk equities/crypto/forex daily; `get_intraday_fallback()` with period retry; `=F` suffix for futures
- `IBKRFeed` — 3-strikes TF-level session disable; circuit breaker (10 failures → 5min cooldown); Warning 1100/1102/2110 handlers; 15s RequestTimeout intraday; 60s batch rest every 50 assets
- `UniverseBuilder` — Phase 1 (yfinance ~10min) + Phase 2 (IBKR hours); cache backfill at return

**How to call from analysis.py:**
```python
from data import UniverseBuilder
from config import Config

builder = UniverseBuilder()
result = builder.build()
# result.data: Dict[str, pd.DataFrame] — keys are "SYMBOL_TFLABEL"
# result.assets: List[Tuple[str, str]] — (symbol, asset_class)
# result.quality_reports: List[QualityReport]
# DataAligner.align_universe(result.data, "1D") — aligns to NYSE calendar
```

---

## config.py — Key Parameters

```python
Config.DATA.TIMEFRAME_LABELS  = ["1m","2m","3m","5m","15m","30m","1h","4h","8h","1D","7D","1M"]
Config.DATA.MIN_BARS_REQUIRED["1D"] = 100   # lowered for futures front-month
Config.UNIVERSE.FUTURES       = ["ES","NQ","RTY","YM","ZN","ZB"]
Config.UNIVERSE.COMMODITIES   = ["GC","SI","CL","NG","ZC","ZW","ZS","HG"]
Config.UNIVERSE.FOREX         = ["EUR.USD","GBP.USD","USD.JPY","USD.CHF","AUD.USD","USD.CAD","NZD.USD","EUR.GBP","EUR.JPY","GBP.JPY"]
Config.UNIVERSE.MIN_PEARSON_CORR    = 0.60
Config.ANALYSIS.OU_LOOKBACK_DAYS    = 252
Config.ANALYSIS.OU_ZSCORE_ENTRY     = 2.0
Config.ANALYSIS.OU_ZSCORE_EXIT      = 0.5
Config.STATS.PBO_N_PARTITIONS       = 16
Config.STATS.FDR_ALPHA              = 0.05
Config.ML.TRAIN_PCT / VAL_PCT / TEST_PCT = 0.60 / 0.20 / 0.20
```

---

## analysis.py — Full Architecture (READY TO BUILD)

**Single file, same pattern as data.py. Use Opus 4.7, normal effort.**

### Classes

**`UniverseFilter`**  
Vectorized Pearson pre-filter. Loads aligned DataFrames for one TF at a time. Computes full N×N correlation matrix in a single numpy operation (sub-second for N=526). Returns candidate pairs above MIN_PEARSON_CORR=0.60. Handles same-class and cross-class pairs identically — tagging happens downstream.

**`CointScanner`**  
Engle-Granger for pairs, Johansen for trios. ProcessPoolExecutor with 12 workers. Each worker gets a batch of pairs, runs `statsmodels.tsa.stattools.coint()`. After all tests: BH-FDR correction per TF. Also runs rolling 252-day cointegration — reports fraction of windows where EG is significant (not just full-sample result).

**`HedgeRatioEstimator`**  
Three methods computed for every confirmed pair:
- OLS (primary): rolling 252D window, standard regression
- TLS (comparison): total least squares via SVD — symmetric, no direction assumption
- Kalman (comparison): dynamic hedge ratio, state-space model, updates each observation
All three stored. OLS used for primary z-score.

**`SpreadModel`**  
OU process. Computes: spread, rolling mean/std, z-score, half-life (-ln(2)/log(AR1 coeff)), mean reversion speed θ. Both rolling 252D (primary) and expanding window (comparison). Difference in half-life estimates between methods flags structural instability.

**`VolumeStructure`**  
Features from OHLCV + vwap field:
- Relative volume: current / rolling N-day same-time-of-day average (intraday seasonality normalized)
- Dollar volume: price × volume
- VWAP deviation: (close - vwap) / vwap
- Amihud illiquidity: |return| / dollar_volume
- CVD proxy: cumulative (buy_vol - sell_vol) using bar tick rule (close>open=buy)
- Large-move low-volume flag: |return|>2σ AND volume<0.5× avg
- High-volume small-move flag: volume>2× avg AND |return|<0.5σ
- Volume divergence: price making N-bar high while volume declining
- Open interest: futures/commodity assets only (IBKR field if available)

**`RegimeClassifier`**  
K-means + GMM + HMM, all three run and compared. Auto-K selection: silhouette (K-means), BIC (GMM/HMM), K=2–6. Feature aggregation at 10, 20, 40 bars — all tested, optimal selected per asset. All features volatility-standardized before clustering (feature / rolling std). Expanding-window constraint — no regime lookahead. Three conditioning variants: A (signal valid only in mean-reverting regime), B (signal valid when both legs above-average volume), C (baseline, no conditioning).

**`StrategyDecayDetector`**  
- Rolling coint fraction: fraction of 252D windows where EG is significant
- Half-life trend: linear trend on rolling half-life estimates (positive slope = decaying)
- Structural break tests: Zivot-Andrews, CUSUM
- IS/OOS Sharpe decay ratio per WFA window

**`ThresholdCalibrator`**  
Sensitivity analysis for Pearson pre-filter (0.45–0.75, 0.05 steps) and Johansen significance (0.01, 0.05, 0.10). Plots inflection curves. Empirically justifies the 0.60 threshold choice. Also runs full parameter sensitivity: OU lookback (126, 252, 504D), half-life ceiling (30, 60, 90, 120D), z-score entry (1.5, 2.0, 2.5, 3.0), BH-FDR α (0.01, 0.05, 0.10). Identifies stability region — contiguous parameter space where results stay within 1σ of baseline.

**`TrioBuilder`**  
A↔B + B↔C → test A↔B↔C with Johansen multivariate test. Both constituent pairs must exceed TRIO_MIN_PAIR_SHARPE=1.0. Cap at 500 candidates.

**`CrossAssetTagger`**  
Tags pairs where legs are from different asset classes. Separate results structure. Own section in report.

**`BiasAuditLog`**  
Running log written during pipeline execution. Records every decision point where a bias remedy was applied. Feeds dedicated bias audit chapter in report. Tracks: lookahead (rolling/expanding window usage), multiple testing (BH-FDR application), non-stationarity (rolling vs full-sample coint), regime identification (expanding-window constraint).

**`SyntheticBarBuilder`** (optional variant)  
Dollar bars from 1-minute OHLCV for high-liquidity subset (top 50 S&P 500 by dollar vol + ES + NQ). Parallel analysis pipeline on synthetic bars vs time bars. Comparison of cointegration stability becomes Section 6b in report.

**`AnalysisPipeline`**  
Orchestrator. Memory-efficient: processes one TF at a time. Loads aligned data from DataAligner. Runs full class chain. Saves results to `output/results/{tf_label}/` as Parquet. Returns `AnalysisResults` dataclass consumed by ml.py and report.py.

### Results Schema (per confirmed pair × TF)
```
date, spread, spread_zscore_rolling, spread_zscore_expanding,
hedge_ratio_ols, hedge_ratio_tls, hedge_ratio_kalman,
half_life_rolling, half_life_expanding, mean_reversion_speed,
regime_kmeans, regime_gmm, regime_hmm,
vol_condition_a, vol_condition_b,
relative_vol_a, relative_vol_b, amihud_a, amihud_b,
vwap_dev_a, vwap_dev_b, cvd_proxy_a, cvd_proxy_b,
rolling_corr_60d, rolling_corr_252d, corr_velocity,
coint_pvalue_fullsample, coint_fraction_rolling,
is_cross_asset, asset_class_a, asset_class_b,
source_a, source_b
```

### Processing Architecture
- One TF at a time through full pipeline (memory management)
- ProcessPoolExecutor(max_workers=12) for EG tests
- BH-FDR applied per TF after all tests complete
- Daily TF scanned first (most reliable, sets baseline pair count)
- Results written to Parquet after each TF completes (crash-safe)

---

## Report Structure (for context)

```
1. Abstract
2. Introduction & Motivation
3. Universe & Data
4. Methodology
   4.1 Co-Movement Detection
   4.2 Spread Model (OU process, hedge ratios)
   4.3 Volatility Framework
   4.4 Regime Classification
   4.5 Signal Conditioning Variants
   4.6 Alternative Bar Construction (synthetic)
5. Machine Learning Signal Discovery
6. Backtest & Position Sizing
7. Sensitivity Analysis
8. Overfitting Validation (WFA, PBO, PSR/DSR, Monte Carlo)
9. Strategy Decay Analysis
10. Bias Audit
11. Results & Discussion
12. Conclusions
```

---

## Model Recommendations

| Task | Model | Effort |
|------|-------|--------|
| Planning/architecture/debugging | Sonnet 4.6 | Normal |
| Writing large files (analysis.py, ml.py etc.) | Opus 4.7 | Normal |
| Hard one-off statistical reasoning | Opus 4.8 | Max |

---

## Preferences & Working Style

- **Comprehension before code:** full logic walkthrough before implementation
- **No bandaid solutions:** root cause fixes only
- **Single best solution:** one correct approach, implemented completely
- **Production-ready output:** no fragments, no truncated files
- **No multiple alternatives:** one solution per problem
- **Firm on parameter changes:** no tuning until statistical thresholds met
- **Single file architecture:** preferred (same as data.py)
- **User:** Ross W., WSU undergraduate, building for transfer applications + MFE programs