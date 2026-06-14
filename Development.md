# CAMARF Development Log
## Cross-Asset Co-Movement Arbitrage Research Framework
**Repository:** github.com/rossw811/CAMARF  
**Author:** Ross W. — Washington State University  
**Version:** 1.0.0 (Active Development)

---

## Table of Contents
1. [Project Architecture](#project-architecture)
2. [Script Reference](#script-reference)
3. [Data Pipeline: `data.py`](#data-pipeline-datapy)
4. [Challenges, Problems & Fixes](#challenges-problems--fixes)
5. [Data Source Findings](#data-source-findings)
6. [Known Limitations](#known-limitations)
7. [Development Session Log](#development-session-log)

---

## Project Architecture

CAMARF is a multi-asset statistical arbitrage research framework. The codebase is organized into eight domain-scoped files:

| File | Domain | Status |
|------|--------|--------|
| `config.py` | All parameters, universe lists, flags | ✅ Complete |
| `data.py` | Universe building, data acquisition, cleaning, caching | ✅ Complete |
| `analysis.py` | Co-movement scan, spread model, vol framework, regimes | 🔄 Planned |
| `ml.py` | Feature engineering, classifier, feature selection | 🔄 Planned |
| `backtest.py` | Engine, combinatoric testing, position sizing | 🔄 Planned |
| `options.py` | IV surface, IV signal layer | 🔄 Planned |
| `stats.py` | Significance tests, Monte Carlo, WFA, PBO, PSR, PCA | 🔄 Planned |
| `report.py` | PDF assembly, all section builders | 🔄 Planned |

---

## Script Reference

### `config.py`
Central configuration. Single import point for all modules via the `Config` master class.

**Key classes:**
- `IBKRConfig` — Gateway connection parameters (host, port, clientId, readonly mode)
- `DataConfig` — Timeframes, history depths, quality thresholds, cache paths
- `UniverseConfig` — Asset lists (S&P 500 dynamic, crypto, forex, commodities, futures) and pre-filter thresholds
- `AnalysisConfig` — Engle-Granger/Johansen parameters, OU spread model settings, regime classification settings
- `MLConfig` — Target variable definition, feature engineering parameters, model hyperparameters, train/val/test split
- `BacktestConfig` — Account sizes, sizing methods, grid search parameters, walk-forward settings, circuit breakers
- `OptionsConfig` — IV surface interpolation, IV spread signal parameters
- `StatsConfig` — Monte Carlo settings, PSR/PBO parameters, FDR threshold, PCA variance target
- `ReportConfig` — Page layout, color palette, output filename

**Important design notes:**
- `MIN_BARS_REQUIRED` is a per-timeframe dict, not a global threshold. Monthly bars at 24 minimum, daily at 100 (lowered from 500 to accommodate futures front-month contracts with naturally limited history).
- `TIMEFRAMES` uses exact IBKR bar size strings. `12 hours` is invalid (confirmed via IBKR Error 321). `1W` and `1M` use IBKR's exact format, not `"1 week"` / `"1 month"`.
- `GC` (Gold) and `CL` (Crude Oil) appear only in `COMMODITIES`, not `FUTURES`, to prevent duplicate fetches.

---

### `data.py`
Universe building, data acquisition, cleaning, and caching. The most complex file in the codebase — handles five fundamentally different data sources and their edge cases.

**Class overview:**

#### `DataStore`
Parquet cache layer. All other classes read/write through here.
- `save(symbol, tf_label, df)` — write DataFrame to `output/cache/{symbol}_{tf_label}.parquet`
- `load(symbol, tf_label)` — return DataFrame or None
- `is_fresh(symbol, tf_label, max_age_hours=None)` — returns True if file exists (permanent cache unless max_age_hours specified)
- `list_cached()` — list all cached symbol-timeframe combinations

#### `ProgressLogger`
Crash-safe progress tracking with config-hash invalidation.
- `compute_config_hash()` — SHA-256 of all config parameters affecting data validity
- `load()` / `save(progress)` — read/write `output/cache/progress.json` atomically
- `mark_complete(progress, symbol, asset_class, timeframes_done)` — persist after every successful asset
- `is_complete(progress, symbol)` — True only if asset was fetched under current config hash
- `reset()` — delete progress file to force full re-fetch

**Config hash invalidation:** if any parameter affecting data validity changes (timeframes, history depth, quality thresholds, universe lists), all previously cached assets are re-fetched automatically.

#### `DataAligner`
Aligns all assets to a common NYSE trading calendar timeline.
- `align_daily(data, start_date, end_date)` — reindexes to NYSE master calendar, forward-fills gaps, adds `is_gap: bool` column, excludes assets with >50% gaps
- `align_intraday(data, tf_label)` — within-session alignment, flags gaps, drops overnight breaks
- `align_universe(universe_data, tf_label)` — top-level method called by `analysis.py`

**Design decision:** Option A (NYSE calendar as master for all asset classes). Forex and futures forward-fill on NYSE holidays. Every asset gets identical DatetimeIndex, required for pairwise cointegration calculations.

#### `DataCleaner`
Pure static pipeline. Takes raw OHLCV DataFrame, returns cleaned DataFrame + QualityReport.

Pipeline order:
1. Standardize column names to lowercase; promote `date` column to DatetimeIndex (critical — ib_insync returns RangeIndex + date column, not DatetimeIndex)
2. Remove duplicate timestamps
3. Gap detection and forward-fill (NYSE calendar for daily, skipped for intraday — overnight gaps are not data gaps)
4. Roll adjustment for futures (>5% single-bar return = candidate roll date, backward ratio adjustment applied)
5. Dollar-volume liquidity filter for equities
6. Minimum bar count validation (per-timeframe threshold from config)

**`source` field:** QualityReport tracks data provenance — `"ibkr"`, `"yfinance"`, or `"yfinance_resampled"`. Used to document data source distribution in the methodology section.

**VWAP:** IBKR's `average` field (bar-level VWAP) is retained and renamed to `vwap`. Previously dropped — restored to enable VolumeStructure features in `ml.py`.

#### `YFinanceFeed`
Bulk equity data via yfinance. Handles equities, crypto (`BTC-USD`), and forex (`EURUSD=X`).

**Data source strategy:**
- Fetches daily/weekly/monthly only (yfinance intraday is too shallow for primary use)
- 4h/8h intraday NOT available from yfinance natively — derived by resampling 1h bars
- 3m derived by resampling 1m bars (same 42D depth, no loss)
- Download in chunks of 50 tickers with individual retry for failures

**MultiIndex extraction:** yfinance returns `(Price, Ticker)` MultiIndex by default. Uses level-0 fallback if level-1 extraction fails (handles both `group_by` configurations). **Critical bug fixed:** `group_by="ticker"` puts tickers at level 0, breaking level-1 extraction — removed `group_by` from download call.

**Fallback period retry:** When `period=730d` fails for new listings (e.g. GEV spun off April 2024), automatically retries with `period=60d`. Working period cached to DataStore to avoid repeated failures.

**Caches:**
- `output/cache/sp500_tickers.json` — S&P 500 ticker list, 24h expiry
- `output/cache/yf_period_{symbol}_{interval}.parquet` — working yfinance period per ticker/interval

#### `IBKRFeed`
IBKR Gateway connection for non-equity asset classes and equity intraday data.

**Rate limiting architecture:**
- Base delay: 5s between requests
- Intraday delay: 12s between intraday requests
- Every 3rd consecutive intraday request: +10s buffer
- Every 5 total session requests: 15s floor
- Every 50 assets in the interleaved loop: 60s batch rest (prevents HMDS sustained overload)

**Circuit breaker:**
- `_consecutive_fails` — increments on every IBKR failure, resets only on IBKR success (not yfinance success)
- After 10 consecutive failures: circuit opens, 5-minute cooldown, routes to yfinance
- **3-strikes system:** tracks `_tf_ibkr_attempts` and `_tf_ibkr_successes` per TF sweep. After 3 IBKR attempts with 0 successes, that TF is disabled for the entire session (`_tf_ibkr_disabled` set)
- Error 1100 handler: opens circuit immediately on IBKR connectivity loss
- Error 1102 handler: schedules circuit reset after 30s stabilization

**Contract resolution (futures):** Uses `reqContractDetails` (not `qualifyContracts` which raises on ambiguous contracts). Filters to unexpired expiry dates, sorts ascending, selects front month. Results cached to `output/cache/contracts/{symbol}.json` with 30-day expiry.

**`RequestTimeout`:** 15s for intraday (fail fast → yfinance fallback), 30s for daily.

**yfinance fallback:** When IBKR returns empty or 1 bar, immediately tries `YFinanceFeed.get_intraday_fallback()`. Fallback maps each IBKR TF label to the closest available yfinance interval, resampling where necessary.

#### `CBOEFeed`
Options IV surface data from CBOE's public delayed quotes API.
- Parses OCC option code format (regex-based, handles symbols like `AAPL` containing `P`)
- Filters to config moneyness range (0.80–1.20) and DTE range (7–90 days)
- Constructs mid-IV surface from call/put pairs
- Session-level in-memory cache + DataStore Parquet cache

#### `UniverseBuilder`
Orchestrates the full data pipeline. Returns `UniverseResult` consumed by all downstream modules.

**Two-phase architecture:**
- **Phase 1 (yfinance, ~10 minutes):** Equities + crypto + forex, daily/weekly/monthly only. Bulk chunked downloads of 50 tickers. Includes per-ticker retry for failed downloads.
- **Phase 2 (IBKR, hours):** Equity intraday (interleaved TF-first loop), forex intraday, commodities, futures. Non-equity daily fetched with 2s delay between contracts.

**Interleaved intraday loop:** TF as outer loop, assets as inner loop. Prevents IBKR same-contract pacing (by the time we return to ABT for 8h, 500+ other contracts have been requested). Resets circuit state between TF sweeps.

---

## Data Pipeline: `data.py`

### Data Source Map

| Asset Class | Daily/Weekly/Monthly | Intraday |
|---|---|---|
| S&P 500 Equities | yfinance (bulk, ~10min) | IBKR → yfinance fallback |
| Crypto | yfinance (`BTC-USD`) | IBKR → yfinance fallback |
| Forex | yfinance (`EURUSD=X`) | IBKR → yfinance fallback |
| Commodities | IBKR | IBKR → yfinance fallback |
| Futures | IBKR | IBKR → yfinance fallback |

### Timeframe Strategy

| TF | Source | Depth | Notes |
|---|---|---|---|
| 1D | yfinance / IBKR | 20Y equities, varies others | Primary analysis TF |
| 7D | Resampled from 1D | Same as 1D | No depth loss |
| 1M | Resampled from 1D | Same as 1D | No depth loss |
| 4h | IBKR → yfinance | IBKR: 10Y / yf: ~730D | IBKR 4h disabled on paper accounts (confirmed) |
| 8h | IBKR → yfinance | IBKR: 10Y / yf: ~730D | |
| 1h | IBKR → yfinance | IBKR: 5Y / yf: 730D | |
| 30m | IBKR → yfinance | IBKR: 2Y / yf: 60D | |
| 15m | IBKR → yfinance | IBKR: 1Y / yf: 60D | |
| 5m | IBKR → yfinance | IBKR: 6M / yf: 60D | |
| 3m | Resampled from 1m | 42D | Not available natively in yfinance |
| 2m | Resampled from 1m | 42D | Same depth as 1m |
| 1m | IBKR → yfinance | IBKR: 42D / yf: 7D | |

---

## Challenges, Problems & Fixes

### 2026-06-10: Wikipedia 403 on S&P 500 fetch
**Problem:** Plain urllib requests blocked with HTTP 403.  
**Fix:** Added browser `User-Agent` header. Three-source fallback: Wikipedia → iShares IVV CSV → hardcoded top-50.  
**Later improvement:** 24-hour local cache to avoid fetching every run.

### 2026-06-10: `insufficient_bars_1` on all equities
**Problem:** Every equity returning exactly 1 bar from IBKR. `DataCleaner._standardize()` was treating `date` column as non-OHLCV and dropping it. ib_insync returns bars with `RangeIndex` + `date` column, not `DatetimeIndex`. After dropping `date`, gap-fill built index from timestamp `0` to `0` → 1 row.  
**Fix:** Promote `date` column to DatetimeIndex as first step in `_standardize()`.

### 2026-06-10: `ADJUSTED_LAST` fails for weekly/monthly equity bars
**Problem:** IBKR Error 321 — "Multi day bar size not supported with adjusted last."  
**Fix:** `_what_to_show()` now returns `ADJUSTED_LAST` only for `1 day` equity bars. Weekly and monthly use `TRADES`.

### 2026-06-10: `missing_pct_0.036_exceeds_threshold` on all equities
**Problem:** pandas `"B"` frequency generates every weekday but not market holidays. US equity markets have ~3.6% of business days as holidays (MLK Day, Presidents Day, etc.), causing 3.6% "missing" bars that are actually correct.  
**Fix:** Switched to `pandas_market_calendars` (NYSE calendar) for daily gap detection. `MAX_MISSING_PCT` raised from 2% to 10%.

### 2026-06-10: `12 hours` is not a valid IBKR bar size
**Problem:** Error 321 — bar size invalid. IBKR legal sizes don't include `12 hours`.  
**Fix:** Removed from `TIMEFRAMES`. Now 10 timeframes (later expanded to 12 with 2m and 3m).

### 2026-06-10: `7D` and `1M` fail with `ADJUSTED_LAST`
**Problem:** Error 321 — "Multi day bar size not supported with adjusted last."  
**Fix:** `TIMEFRAMES` updated to use `"1W"` and `"1M"` (IBKR's exact format). Weekly/monthly equity bars use `TRADES`. Both TFs are now derived by resampling from 1D.

### 2026-06-11: IBKR intraday timeout (1 minute per request)
**Problem:** `reqHistoricalData` with `endDateTime=""` for intraday bars on paper accounts fails silently, timing out after 60 seconds.  
**Fix:** Explicit `endDateTime` using current UTC time for all intraday bar sizes. `nest_asyncio.apply()` added for Windows asyncio compatibility.

### 2026-06-11: Futures "Ambiguous contract" with `qualifyContracts`
**Problem:** `qualifyContracts` raises an exception when multiple expiry months match (e.g. CL returns 100+ contracts). Exception caught → returned `None`.  
**Fix:** Switched to `reqContractDetails` which returns all matches without raising. Filter to unexpired expiry dates, sort ascending, select front month. Results cached 30 days.

### 2026-06-11: yfinance MultiIndex extraction failure (523 of 503 excluded)
**Problem:** `group_by="ticker"` in `yf.download()` puts tickers at level 0 of the MultiIndex. Code checked level 1 → every lookup returned False → every asset got `None` → excluded.  
**Fix:** Removed `group_by="ticker"`. Added dual-level fallback: try level 1 first (standard), then level 0.

### 2026-06-12: Crypto "No market data permissions for PAXOS CRYPTO"
**Problem:** IBKR paper account doesn't have crypto subscription.  
**Fix:** Routed crypto to yfinance using `{symbol}-USD` format (e.g. `BTC-USD`).

### 2026-06-12: IBKR 4h bars 100% failing session-wide
**Problem:** Every IBKR 4h request returns empty with no error message. Confirmed across all 526 assets consistently.  
**Root cause:** IBKR HMDS historical data server doesn't support 4h bars on paper accounts (subscription limitation specific to this bar size).  
**Fix:** 3-strikes circuit breaker — after 3 IBKR attempts with 0 successes for a TF, routes all remaining requests to yfinance fallback immediately. Circuit is TF-specific and session-persistent.  
**Data impact:** All 4h bars sourced from yfinance (1707 bars ≈ 730 days). Documented via `source="yfinance"` in QualityReport.

### 2026-06-13: Circuit breaker not firing (yfinance success resetting counter)
**Problem:** `_consecutive_fails` was reset to 0 when yfinance succeeded. Pattern: IBKR fail (count=1) → yfinance success (count=0) → repeat forever, never reaching 10.  
**Fix:** Removed `consecutive_fails` reset from yfinance success path. Only actual IBKR success resets the counter.

### 2026-06-13: HMDS inactive at intraday sweep start (AZO/AVB failures)
**Problem:** HMDS confirmed "inactive" at connection time. Intraday loop started before HMDS fully activated. First 1-3 assets failed while HMDS was transitioning.  
**Fix:** 30-second mandatory pause before interleaved intraday sweep.

### 2026-06-13: IBKR session-level overload (cascade failure after ~100 requests)
**Problem:** Sustained IBKR historical data requests caused HMDS to crash with Error 1100 after ~100 consecutive requests.  
**Fix:** Mandatory 60-second batch rest every 50 assets in the interleaved loop.

---

## Data Source Findings

These are empirically confirmed observations from running `data.py` against a live IBKR paper account (confirmed via `diagnose.py` on 2026-06-11):

1. **IBKR 4h bars are unavailable on paper accounts.** 100% failure rate across all 526 assets. yfinance provides 730-day substitute at the cost of depth (IBKR would give 10 years, yfinance gives ~2 years). All 4h bars tagged `source="yfinance"`.

2. **IBKR 1m bars go back exactly 42 trading days**, not 30 calendar days as documented.

3. **IBKR daily equity data goes back to 2006** (~20 years). `ADJUSTED_LAST` is the correct `whatToShow` for daily equity bars; `TRADES` returns only recent unadjusted data.

4. **yfinance S&P 500 daily data goes back to the 1980s** for most constituents.

5. **IBKR paper accounts enforce stricter intraday pacing** than documented. The 60-request/10-minute limit appears to be enforced more aggressively on paper accounts, requiring 12s+ between intraday requests.

6. **IBKR `reqContractDetails` resolves all futures months** without raising exceptions. `qualifyContracts` raises on ambiguity. Front-month selection: filter to unexpired expiry, sort ascending, take first.

7. **GEV (GE Vernova)** was spun off April 2024. yfinance `period=730d` fails; `period=60d` succeeds with ~120 bars. Working period cached to avoid repeated failures.

---

## Known Limitations

1. **Survivorship bias:** Universe uses current S&P 500 constituents. Assets removed since 2006 (bankruptcy, acquisition, delisting) are absent. Historical analysis is implicitly conditional on survival.

2. **4h bar depth:** All equity 4h bars are yfinance-sourced (~730 days). IBKR would provide ~10 years. Documented in QualityReport via `source` field.

3. **Paper account data restrictions:** Some IBKR bar sizes and data types may be unavailable on paper accounts but available on live accounts. All limitations confirmed and documented.

4. **Crypto intraday:** Crypto intraday data from yfinance has limited depth (1h: 730d, 5m: 60d, 1m: 7d). IBKR crypto not subscribed on current account.

5. **Forex intraday depth:** Similar to crypto — yfinance forex intraday is shallower than IBKR native would provide.

---

## Development Session Log

| Date | Session Focus | Key Outcomes |
|------|--------------|--------------|
| 2026-06-10 | Initial `data.py` build | DataStore, DataCleaner, IBKRFeed, UniverseBuilder |
| 2026-06-10 | IBKR connectivity fixes | Fixed 403, timeout, `ADJUSTED_LAST`, holiday gap detection |
| 2026-06-11 | IBKR bar size validation | Removed 12h, fixed 1W/1M format, added 2m/3m |
| 2026-06-11 | Architecture: yfinance hybrid | Daily via yfinance (10min), intraday via IBKR |
| 2026-06-12 | MultiIndex fix, crypto routing | Fixed level-0/1 bug, routed crypto to yfinance |
| 2026-06-12 | Futures contract resolution | reqContractDetails, front-month selection, 30-day cache |
| 2026-06-13 | Circuit breaker system | 3-strikes, TF-level disable, Error 1100/1102 handlers |
| 2026-06-13 | Caching improvements | S&P 500 ticker cache, contract cache, period cache |
| 2026-06-13 | DataAligner, VWAP | NYSE calendar alignment, is_gap flag, VWAP retention |
| TBD | `analysis.py` | Co-movement scan, OU spread model, regime classification |