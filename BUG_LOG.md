# CAMARF Bug Log — Index

Quick-navigation index into `Development.md`'s bug registry (proposed Session 26, built Session 28,
2026-07-11, per the second-pass staleness triage's #1 actionable item). **This is a pure INDEX, not a
content move** — every entry below is a one-line summary with a `Development.md:LINE` pointer to the
full write-up. Nothing was deleted or moved out of `Development.md`; that file remains the canonical,
complete record. This file exists only so a ~60-entry bug can be found without reading 10,900+ lines
of session narrative to locate it.

To use: find the bug number or keyword below, then open `Development.md` at the given line for the
full root-cause/fix/verification write-up.

## data.py / fetch pipeline (BUG-D)

| # | Summary | Development.md |
|---|---------|-----------------|
| D01 | Futures ambiguous contract — qualifyContracts returns all expiry months | :147 |
| D02 | Forex contract format — wrong pair ordering in ib.Forex() | :149 |
| D03 | OOM on 1m reindex — date_range allocates before size check | :151 |
| D04 | Holiday gap detection using pandas 'B' misses NYSE holidays | :153 |
| D05 | Warning 2110 infinite reconnect — IBKR upstream broken | :155 |
| D06 | yfinance 1m period "7d" exceeds Yahoo's 8-day hard limit | :157 |
| D07 | ADJUSTED_LAST fails weekly/monthly intervals | :159 |
| D08 | MultiIndex group_by="ticker" breaks extraction | :161 |
| D09 | ProgressLogger PermissionError on OneDrive | :163 |
| D10 | Cache backfill returning session-only keys, missed 5,752 disk files | :165 |
| D11 | 7D/1M yfinance weekly inconsistency across asset classes | :167 |
| D12 | period kwarg missing from get_equity_history() | :169 |
| D13 | Completed assets bypass freshness check | :171 |
| D14 | Excluded assets could still enter backfill | :173 |
| D15 | Cache deletion via rename fails on Windows/OneDrive | :1482 |
| D16 | ETF class not in yfinance routing filter | :1804 |
| D17 | 2m/3m derived from corrupted 1m data | :1812 |
| D18 | Batch yfinance saves 0/N bars | :1852 |
| D19 | IBKR session-dead reconnection infinite loop | :1856 |
| D20 | Config hash forces full re-fetch on every config change | :1860 |
| D21 | analysis.py running full IBKR fetch (architecture violation) | :1864 |
| D22 | 8h batch yfinance saves 0/N (persistent) — led to 8h removal | :2249 |
| D23 | 1h cache contaminated with 8h-frequency data (961 assets) | :2253 |
| D24 | 4h derivation produces silent wrong-frequency output | :2510 |
| D25 | RunSummary table empty despite Phase 2A running | :2523 |
| D26 | 2m systematic 100% fetch failure — period interpretation | :2532 |
| D27 | Explicit-date day-count keyed by wrong variable (introduced by D26's wrong-hypothesis-2) | :2547 |
| D28 | yf.download() unreliable for bulk sequential calls vs. yf.Ticker().history() | :2558 |
| D29 | Stale "45d_fallback" string reaching the API as a literal period | :2569 |
| D30 | Missing pytz dependency in the trading conda environment | :2581 |
| D31 | CRITICAL — fresh yf.Ticker() per call triggers Yahoo anti-bot throttling (root cause of 1h/2m/1m failure pattern) | :2587 |
| D33 | _fetch_constituents_cached unconditionally cached empty live-fetch results | :3171 |
| D34 | pd.read_html(resp.text) no longer accepts literal HTML strings on pandas 2.2.3/3.0.3 (universe collapsed to 86 assets) | :3226 |
| D35 | seed_sp_caches.py picked Wikipedia's historical "Selected changes" table instead of current constituents | :3239 |
| D36 | MIN_BARS_REQUIRED['1m']/['3m'] were mathematically impossible to satisfy | :3255 |
| D37 | 4h resample used clock-aligned bins, not session-aligned (contradicts D32's supposed fix) | :3283 |
| D38 | Stale per-ticker yf_period cache entries with no expiry, silently capping ~80 tickers' 1h fetches | :3296 |
| D39 | SEVERE — analysis.py was never actually read-only (Architecture Rule #1 violation) | :3311 |
| D40 | Cache-contamination frequency checks included overnight/weekend gaps, deleting good 4h files | :3345 |
| D41 | Stale 30m cache from an older pipeline version, missing the morning session | :3366 |
| D42 | Supersedes D31's throttling guess — 1m/2m/3m real root cause | :3734 |
| D43 | _write_analysis_summary() crashed on Optional[float]=None hurst_rs | :3818 |
| D44 | ml.py's confirmed-pair discovery — two bugs, same session | :3854 |
| D45 | SpreadModel.fit_pair's rolling z-score/half-life computed on padded, not real, bars | :3911 |
| D46 | Overnight is_fresh() fix was incomplete — one more call site | :4251 |
| D47 | Confirmed-pair counts in latest_run_analysis.log overstated by 2x+ | :4283 |
| D48 | confirmed_pairs_manifest.json only ever accumulated, never pruned | :4329 |
| D49 | Degenerate, repeated-price bars (price degeneracy) — root-caused to market cap, ~32% of 1m universe. Multiple entries as the investigation progressed | :4568, :4832, :5048, :5137, :6006 |
| D50 | CFTC COT API — wrong dataset ID + wrong contract names + wrong URL construction | :6274 |
| D51 | _clean_close() returns np.ndarray, not pd.Series | :6434 |
| D52 | FDR_ALPHA misconfigured — 0.01 too strict for 65k-pair universe, killed valid 1h pairs | :7603 |
| D53 | Permutation test's trade-level shuffle destroyed genuine cross-pair exit-timing correlation, inflating the null | :9600 |
| D54 | research/decoupling_analysis.py — zero GapFlag masking + live/stale directory double-counting | :10073 |
| D55 | stats.py confirmatory validation stack loads unmasked spread_series_*.parquet | :10112 |
| D56 | backtest.py continuous-forecast-scaling STORM flags silently override coint_frac_sizing instead of composing — fixed 2026-07-11 | :10191 (found), :10958 (fixed) |
| D57 | DataCleaner._standardize() strips tz before snap_timestamps() ever sees it — exchange-aware `.L`/`.T`/`.HK` session handling was dead code in real production flow. FIXED — turned out narrower than expected (DataCleaner.clean() itself needed no changes); snap_timestamps() now handles naive-but-already-local input. VOD.L retention 44.5%→88.9%, 7267.T 57.1%→85.9%. Exercised end-to-end through the real production fetch→clean→snap→cache-write path (2026-07-12) — real cache files written and round-trip confirmed for VOD.L/7267.T/0700.HK | :11076 (found), :11472 (fixed) |
| D58 | survivorship_exclusions.csv conflates "removed from S&P 500 index" with "delisted/no longer trading" — silently truncated 7/24 confirmed 1h pairs (DD/NOV/FHN legs) to zero backtest data. FIXED — `resolve_survivorship_oos_end()` only truncates if real data doesn't extend >90 days past the claimed removal date. IS Sharpe 5.17→5.80, OOS 4.39→5.22, all 24 pairs now included | :11322 (found), :11432 (fixed) |
| D59 | distance.py's cointegration portfolio Sharpe was an unweighted mean of noisy per-pair Sharpes (one 6-day thin pair showed Sharpe=114, dragging the mean to 20.435) instead of pooled daily P&L like the distance method uses. FIXED — real pooled figure is 8.542, genuinely comparable to distance's 7.865 | :11378 |
| D60 | No portfolio-level capital constraint anywhere in backtest.py — hub_weights is opt-in (not used in headline runs), MAX_CONCENTRATION_PCT/ACCOUNT_SIZES are defined in config.py but never read anywhere. Peak 27 concurrent positions, $421,252 real notional at worst moment — headline Sharpe assumes capital never validated against any account size. Found, quantified, addressed via new portfolio_sim.py (capital-constrained + mark-to-market replay, all 3 account tiers) — not wired into backtest.py's own production path, Ross's call whether to | :11562 |
| D61 | distance.py's GGR comparison never tested the same date window on both sides — cointegration side used backtest.py's 20% holdout (~7mo), distance side used its own hardcoded 50/50 formation/trading split (~18mo). FIXED — aligned to the same HOLDOUT_PCT convention. Corrected comparison: coint 8.542 (222 trades) vs distance ~28 (only 16 trades/7 days, bootstrap-unstable, direction real but magnitude not estimable) | :11848 |

*(D32 is referenced by D37's title as a prior fix but has no standalone entry of its own in
Development.md — flagging as a numbering note, not filling in a fabricated entry.)*

## analysis.py / architecture (BUG-A)

| # | Summary | Development.md |
|---|---------|-----------------|
| A01 | build_returns_matrix equal-length requirement dropped 98% of universe | :177 |
| A02 | Structural pairs leaking into pairs.parquet | :179 |
| A03 | GOOGL/GOOG not detected as structural (share-class) pair | :181 |
| A04 | HMM convergence warnings fire for any log-likelihood decrease below tol | :183 |
| A05 | OOM guard allocated date_range before checking | :185 |
| A06 | Excluded assets could enter analysis via universe.data | :187 |
| A07 | Hurst estimator wrong domain | :1488 |
| A08 | Nested _fit_one_regime (updated name) | :1808 |
| A09 | INCLUDE_QQQ_EXTRAS/RUSSELL_TOP_N/INCLUDE_BRK_HOLDINGS missing from Config | :1816 |
| A10 | NameError `_canonical_cutoff` not defined | :1868 |
| A11 | _fit_one_regime nested function not picklable | :1872 |
| A12 | `_clean_close` NameError kills all EG testing | :2245 |
| A13 | Bias-relevant — build_returns_matrix() imported but never called _gap_aware_returns | :3332 |
| A14 | output/results/3m/ and output/results/3M/ collide on Windows | :3382 |

## How to add a new bug

When fixing a new bug in `Development.md`, add the write-up there as usual (this file is not where
bug write-ups get authored), then add one row here pointing at it. Keep the summary to one line —
the full context stays in `Development.md`.
