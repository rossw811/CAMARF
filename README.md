# CAMARF — Cross-Asset Co-Movement Arbitrage Research Framework

**Author:** Ross W.  
**Repository:** github.com/rossw811/CAMARF  
**Status:** Active development — analysis pipeline complete, ML and backtest layers in progress

---

## Overview

CAMARF is an institutional-grade quantitative research framework investigating whether cross-asset co-movement relationships exhibit regime-dependent, volatility-normalized arbitrage structure predictable at statistically significant rates using multiclass machine learning — and whether that predictability degrades systematically across timeframes, regimes, and asset class boundaries.

The universe spans 529 assets across six classes: S&P 500 equities (503), forex (10), commodities (8), equity index and Treasury futures (6), and cryptocurrency (5). Analysis covers 12 timeframes from 1-minute to 1-month.

This project serves as a primary portfolio piece for quantitative finance program applications.

---

## Research Thesis

> Cross-asset co-movement relationships exhibit regime-dependent, volatility-normalized arbitrage structure predictable at statistically significant rates using multiclass ML, with predictability degrading systematically across timeframes, regimes, and asset class boundaries.

The paper tests this thesis through a sequential analysis pipeline: cointegration discovery → spread modeling → regime classification → ML signal prediction → walk-forward backtesting → statistical validation.

---

## Repository Structure

```
CAMARF/
├── config.py          — Central configuration (universe, data, analysis, stats params)
├── data.py            — Data pipeline: IBKR + yfinance hybrid, cache management
├── analysis.py        — Co-movement scan, spread models, regime classification
├── ml.py              — Feature engineering + multiclass ML classifier (planned)
├── backtest.py        — Walk-forward backtest with risk management variants (planned)
├── stats.py           — Statistical validation: EVT, DCC-GARCH, permutation tests (planned)
├── options.py         — Options overlay: Heston, CRR, Monte Carlo pricing (planned)
├── report.py          — PDF report generation with all exhibits (planned)
│
├── output/
│   ├── cache/         — Parquet cache for all asset data (never cleared between runs)
│   └── results/       — Analysis outputs per timeframe, cleared when scripts change
│       ├── analysis_hash.json    — Script hash for invalidation
│       ├── bias_audit.json       — All bias remedy log entries
│       └── {tf}/
│           ├── pairs.parquet         — Confirmed cointegrated pairs (non-structural)
│           ├── cross_asset_pairs.parquet
│           ├── trios.parquet
│           ├── regimes.json
│           ├── calibration.json      — Pearson/Johansen threshold calibration (1D only)
│           └── features_{symbol}.parquet
│
└── DEVELOPMENT.md     — Full technical reference, session log, bug history
```

---

## Pipeline Architecture

### `data.py` — Universe Build

Builds and maintains a universe of 529 assets with data at 12 timeframes.

**Sources:**
| Asset Class | Daily | Intraday |
|-------------|-------|----------|
| Equities (503) | yfinance bulk | yfinance (IBKR unavailable on paper accounts) |
| Crypto (5) | yfinance BTC-USD format | yfinance |
| Forex (10) | yfinance EURUSD=X format | IBKR |
| Commodities (8) | IBKR | IBKR |
| Futures (6) | IBKR | IBKR |

**Key features:**
- Crash-safe via `ProgressLogger` (resume after interruption)
- Config-hash-aware cache invalidation
- Incremental daily refresh — appends new bars rather than full re-fetch
- IBKR circuit breaker: 3-strikes per TF, automatic fallback to yfinance
- Exclusion list: `VLTO`, `BNY`, `FDXF` (persistently unavailable)
- `DataAligner` aligns to NYSE master calendar (daily) or trading-hours grid (intraday)

### `analysis.py` — Co-Movement Analysis

Processes each timeframe independently, writing results to disk after completion.

**Per-TF pipeline:**
1. **UniverseFilter** — Three parallel pre-filters:
   - Pearson full-sample correlation (primary)
   - Spearman rank correlation (robust to outlier returns)
   - Rolling-average correlation (mean of last 5 × 252-bar windows, decay-aware)
   - Distance correlation / dCor (nonlinear, optional — enabled for 1D)
   - Each pair tagged with `confidence_tier`: gold (all three), silver (two), bronze (one)

2. **CointScanner** — Parallel Engle-Granger on all candidates (12 workers)
   - Benjamini-Hochberg FDR correction per timeframe
   - Rolling 252-bar cointegration fraction (strategy decay signal)

3. **HedgeRatioEstimator** — Three methods per pair:
   - OLS rolling 252-bar (primary, no lookahead)
   - TLS via SVD (symmetric, comparison)
   - Kalman filter with calibrated Q/R (dynamic, comparison)

4. **SpreadModel** — OU fit on residual spread:
   - Rolling and expanding z-scores
   - Half-life (rolling median, full-sample, trend slope for decay detection)
   - Mean reversion speed θ

5. **VolumeStructure** — 12 microstructure features per asset:
   relative volume, dollar volume, VWAP deviation, Amihud illiquidity,
   CVD proxy (tick rule), large-move/low-vol flag, high-vol/small-move flag,
   volume divergence, squeeze indicator (BB/KC ratio), RSI-14, relative vol ratio

6. **RegimeClassifier** — K-means + GMM + HMM with auto-K:
   - Silhouette score selection (K-means), BIC selection (GMM, HMM)
   - Three aggregation windows (10, 20, 40 bars), best selected per method
   - Volatility-standardized features before clustering

7. **StrategyDecayDetector** — Structural break tests:
   - Zivot-Andrews / Quandt break-point (endogenous break date)
   - CUSUM excursion detection (parameter instability)

8. **CrossAssetTagger** — Structural pair exclusion:
   - Forex triangular arbitrage (EUR.USD ↔ EUR.GBP share EUR — mathematical identity)
   - Same-company share classes (GOOGL/GOOG, FOXA/FOX — structural cointegration)
   - Structural pairs logged to bias audit, excluded from primary findings

9. **TrioBuilder** — Johansen multivariate cointegration on trio candidates
   from confirmed-pair adjacency graph

10. **ThresholdCalibrator** — Pearson sensitivity curve + Johansen significance
    sensitivity (1D only — methodology section input)

**Script-hash invalidation:** at each run, SHA-256 of `analysis.py` + `config.py`
is compared to the stored hash. If changed, `output/results/` is cleared before
the pipeline runs, ensuring results always correspond to the current code.

---

## Confirmed Results (Latest Complete Run — 87.7 min)

| TF | Pairs | Cross-Asset | Trios | Regimes |
|----|-------|-------------|-------|---------|
| 1m | 2 | 0 | 0 | 4 |
| 2m | 2 | 0 | 0 | 4 |
| 3m | 2 | 0 | 0 | 4 |
| 5m | 0 | 0 | 0 | 0 |
| **15m** | **5** | **3** | **3** | **8** |
| 30m | 0 | 0 | 0 | 0 |
| **1h** | **6** | **0** | **4** | **9** |
| **4h** | **3** | **0** | **1** | **5** |
| 1D | 3* | 0 | 1 | 5 |
| **7D** | **3** | **0** | **0** | **6** |
| 1M | 2 | 0 | 0 | 4 |

*1D pairs are forex triangles (structural, excluded from primary findings)

**Selected confirmed pairs:**
- `NTRS ↔ STT` (equity-equity, custody banks) — half-life 13.5 bars, coint_fraction 0.917
- `SHW ↔ UNP` (equity-equity) — half-life 12.8 bars, coint_fraction 0.750
- `ES ↔ LNT`, `ES ↔ ETR`, `ES ↔ PNW` (futures-equity, cross-asset at 15m)
- `FITB ↔ TFC`, `KEY ↔ TFC`, `KEY ↔ PNC` (equity-equity, regional bank sector at 1h)
- `JNJ ↔ PG` (equity-equity, consumer defensive at 7D)
- `ADP ↔ DOV` (equity-equity at 7D)

---

## Running the Pipeline

```bash
# Full data fetch (first run ~45 min, subsequent runs ~8 min with incremental refresh)
python data.py

# Full analysis across all 12 timeframes (~90 min)
python analysis.py

# Single timeframe for debugging
python analysis.py --timeframes 1D --no-calibration

# Force clear results regardless of hash
# (add force=True to clear_stale_results call in main())
python analysis.py
```

---

## Key Design Decisions

**No `max(1, contracts)` floor:** position sizing never implicitly uses margin.
At small account sizes, the floor forces margin on every undersized trade.
All positions route to micro contracts (MNQ/MES) when the risk budget can't
fund a standard contract.

**BH-FDR per timeframe:** multiple testing correction applied independently
per TF, not globally. Global correction would be too conservative given
that TFs represent genuinely different signal regimes.

**Pairwise-complete correlation:** all correlation matrices use only the
overlapping valid observations between each pair, not a common fixed window.
This preserves shorter-history assets (recent IPOs, spun-off entities) in
the universe without contaminating correlations with NaN-filled periods.

**Structural pair exclusion:** forex triangles and same-company share classes
are mathematically guaranteed to be cointegrated and are excluded from
primary findings. They appear in `bias_audit.json` for documentation.

**Incremental cache:** `DataStore.append()` adds only new bars to existing
daily parquet files. Re-running `data.py` after a market session appends
the new bars without re-fetching history.

---

## Planned Extensions

- `ml.py` — Multiclass supervised classifier (strong_converge / weak_converge / no_move / diverge_further), TSMOM + CTSMOM features, Hurst exponent, realized skewness, SHAP feature importance, PBO validation
- `backtest.py` — Walk-forward backtesting, strategy Greeks (Δ Γ ν θ ρ), MAE/MFE analysis, delta-neutral variants, portfolio optimization (MV, risk parity, max diversification)
- `stats.py` — EVT tail risk (GPD), DCC-GARCH dynamic correlations, Phillips-Ouliaris + KPSS confirmatory cointegration, permutation test / White reality check
- `options.py` — Heston model calibration to CBOE IV surface, CRR binomial tree, Monte Carlo path-dependent pricing
- `report.py` — Full PDF report with bias audit chapter, factor contribution matrix (12 × 12), heatmaps, Pearson calibration curve, SHAP waterfall plots

---

## Dependencies

```
Python 3.10+
ib_insync          # IBKR API
yfinance           # Market data fallback
pandas / numpy     # Core data manipulation
statsmodels        # Cointegration tests (EG, Johansen), OLS
scikit-learn       # K-means, GMM, StandardScaler, silhouette score
hmmlearn           # Hidden Markov Model
scipy              # SVD (TLS hedge ratio), stats
pyarrow            # Parquet I/O
```