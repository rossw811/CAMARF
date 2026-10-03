# Inconsistency sweep — 2026-09-27 (Ross: "find all these")

Scope: every production module and research script. Target: things that disagree with each other — the same concept
computed two ways, labels/units/calendars that don't line up across sources, silent fallbacks, constants that shadow
config. Every entry is verified against code or real data before it is listed; "checked, consistent" entries are
kept too, so the sweep's coverage is visible. Fixes follow the project rules (failing test first, root cause, backups).

## Categories and status

| # | Category | Status |
|---|---|---|
| 1 | Labels / identity across sources and asset classes | D16, D17 fixed; loader disjoint-source rule |
| 2 | Units and scale | macro thresholds consistent; pence vs pounds pending FX/ADR check |
| 3 | Calendars and time | D13, M8/M9, U2/U3 fixed; weekend-exit booking (S1) |
| 4 | Duplicated logic that has drifted | Sharpe: consistent after P1; `_eg_pvalue`, `build_spread_z`, `load_log_close`, `_load_spread` pending |
| 5 | Constants shadowing config | pending |
| 6 | Silent fallbacks | M13 retry loop swallowed errors (fixed for the new guard); systematic grep pending |
| 7 | Price column semantics (close / close_total_return / close_usd) | D18 open |

## Findings

**M13 FIXED (first published here as "M12", an ID already used by a different review finding — renamed 2026-10-03) — CFTC COT E-mini Nasdaq history truncated to 2022.** `macro.COTFeed` matched contracts by name prefix.
CFTC renamed the contract ("E-MINI NASDAQ 100 STOCK INDEX" 1999; "NASDAQ-100 STOCK INDEX (MINI)" 1999-2022 at IMM
then CME; "NASDAQ MINI" 2022-), and the prefix "NASDAQ MINI" matched only the last: NQ positioning began 2022-02-08
(242 weeks) instead of 1999-06-29 (1,422 weeks). ES was complete (its three names share the prefix; 0 duplicate
dates). Fix: exact chronological name lists; one-row-per-report-date guard that now fails loudly (the fetch's retry
loop swallowed every exception at debug level). Test `_verify_cot_contract_history.py` 4/4 (live). Macro regime
suite 25/25. My first test draft required ≤3-week gaps everywhere — ES has genuine 14-25 day gaps in 1998 (first
year of E-mini reporting); the check was narrowed to the rename boundaries.

**S1 OPEN (minor) — weekend exits booked on the preceding Friday.** `portfolio_math.daily_pnl_from_exits` conserves
P&L but books a Saturday/Sunday exit (24/7 assets) on the Friday BEFORE it happened. Harmless for Sharpe; slightly
early for equity-curve / drawdown timing and any join with other daily series. The following Monday is the honest date.

**Checked, consistent — Sharpe implementations.** 18 definitions outside `portfolio_math`. Every one that feeds a
result builds its daily series through `portfolio_math.daily_pnl_from_exits`/`daily_pnl_from_trades` (business days,
zero-filled over the evaluation window) and then applies mean/std·√252; the remaining standalone formulas
(`stats._portfolio_sharpe`, `regime_conditional_entry_gate._sharpe`, `decay_proxy._window_sharpe` (unannualized,
used as a ranking score), portfolio-optimiser objectives) take an already-built series. ddof differs (0 vs 1) —
negligible.

**Checked, consistent — macro regime thresholds vs units.** T10Y2Y (pp, −1.08..2.91) vs 0.0/1.5; HY OAS and BAA10Y
(percent) vs percent thresholds; VIX level vs 15/25/35; VXV/VIX ratio vs 0.95/1.00/1.10; COT net spec (fraction of
OI, −0.51..0.61) vs −0.10/0.15; Sahm (pp, max 9.43 in 2020) vs 0.5. Known, documented limit: HY OAS only 752 days
(keyless FRED cap), so `credit_regime` is never "wide".

**C4-1 FIXED — WFA fold Sharpe annualized per-TRADE P&L by √(bars/year).** `wfa._fold_metrics` still had the bug
`backtest.compute_metrics` fixed on 2026-09-04 (the fix was never propagated): a per-trade series treated as a per-bar
series. Monthly trades on a 1D pair read 4.10 instead of 0.91 (~4.5× high); the 4h entry also used 252 bars/year
instead of 2×252. One implementation now: `portfolio_math.trade_frequency_sharpe` (√(trades/year) over first entry ..
last exit), used by both. Test `_verify_wfa_trade_sharpe.py` 0/3 → 3/3 (backtest and WFA agree); existing
`_verify_compute_metrics_sharpe_annualization_fix.py` 5/5. **Every WFA fold Sharpe produced before this is wrong.**

**C6-1 FIXED — WFA silently used stale spreads.** `wfa._load_spread` fell back to `output/results/<tf>_stale/` when the
current spread file was missing. Now current-only; a stale file is logged and skipped. Test 1/2 → 2/2. (No `_stale`
directories exist on the Surface; CachyOS to be checked.)

**C6-2 SURFACED — legacy capital-sim charged zero notional for legs with no price.** `portfolio_sim.notional_at_entry`
prices legs from a registered series or the yfinance 1h cache; most WRDS-only symbols have neither, so in
`pnl_mode="legacy"` such trades were silently skipped (both legs missing) or under-charged capital (one leg). The
current dollar mode takes notional from `pnl_dollar` and is unaffected. Legacy behaviour kept (its results are being
withdrawn per PAPER_SCRUTINY) but the count is now logged and returned (`n_missing_leg_price`). Replay suites pass.

**C4-2 OPEN — research EG p-values differ from production's.** `eg_permutation_check._eg_pvalue`,
`lead_lag_scan._eg_pvalue`, `smoothing_comparison._eg_pvalue` test `a[isfinite(a)&isfinite(b)]` — splicing across
genuine data gaps (production's `_eg_worker` keeps the longest gap-free run, BUG-D77) — and one direction only
(production combines both). `eg_permutation_check` backs a PAPER.md claim (line ~3290), `lead_lag_scan` FINDINGS
#27-area claims. **Scope is wider than three copies:** `lead_lag_scan._eg_pvalue` is imported by
`cross_timeframe_divergence`, `lag_sweep_validation`, `lead_lag_permutation_check`, `cross_tf_lead_lag_scan` (and
`eg_permutation_check._eg_pvalue` by `descriptive_check_concordance`). **Not swapped in place, deliberately:** the
permutation scripts compact real and null draws to ONE fixed overlap mask so both have the same N (a documented
2026-07-20 fix); replacing only the real p-value with production's gap-aware two-direction value would break that
like-for-like design. **Plan:** `analysis.eg_pvalue_pair` (added; production's `_eg_worker` both directions, max rule)
is the single API. Non-permutation callers switch to it passing NaN-preserving arrays + tf_label; permutation callers
first select production's gap-free segment, then run real and every null draw on that segment in both directions.
Re-derive and compare old vs new numbers for each affected finding before any is cited.

**M-1 OPEN (methodology, for Ross) — non-like-for-like null in `trend_dominance_diagnostic.leg_corrected_pvalue`.**
The real pair's EG statistic is computed on contemporaneous, date-aligned data; the null distribution comes from
random partners right-aligned by COUNT after dropping NaNs (non-contemporaneous by design). The real statistic shares
the market factor, the null does not, so the correction is biased. Same design in `eg_null_calibration_montecarlo`,
where it is the intended null ("unrelated and non-contemporaneous") — worth stating that it is not the
"unrelated but contemporaneous" null a reader might assume.

**Checked, disclosed — full-sample OLS spreads.** `research/spread_construction.full_sample_ols_spread` (non-causal
hedge ratio) is used by 5 research scripts; its docstring and every caller state it is not point-in-time.

**Stale test fixed — `_verify_pdr_calmar.py`.** Expected Calmar used 9 calendar days (pre-P1); the business-day basis
gives 6 days (Saturday exit booked Friday), matching the code's 5,317.26. Expectation now derived, not hard-coded.

**C1-3 FIXED — loader dedupe could not see an alias whose history ends earlier.** `dedupe_identical_series` bucketed
symbols by their LAST 60 (date, return) values, so a same-security label with a shorter history (a delisted PERMNO
alias) was never compared and discovery could pair it with itself. Now bucketed by the first AND last 60 values;
an alias sharing neither end is caught by the new pair-level check `research/clean_pool_identity_pairs.py`, which
replaces the ad-hoc `clean_pools.py` (it read a side-effect file of the spread regeneration) and decides identity
from the data (≥99% identical daily returns over ≥60 common days). Tests: `_verify_clean_pool_identity_pairs.py` 4/4
(the loader-miss check failed before the fix), `_verify_dedupe_identical_series.py` 5/5.

**C0-1 (minor) — `DEVELOPMENT.md` vs `Development.md`.** Git tracks `Development.md`; CLAUDE.md and other docs say
`DEVELOPMENT.md` — resolves on Windows, not on case-sensitive CachyOS.

## 2026-09-28 additions

**C6 audit — silent broad `except` handlers.** AST scan of 13 production modules: 62 broad handlers that neither log
nor re-raise (data.py 26, analysis.py 18, stats.py 6, universe_loader 4, ml 3, portfolio_sim 2, backtest/pnl_dollar/
data_wrds 1 each). 36 in result-affecting modules triaged by context; most are benign (cleanup, optional model fits,
worker results that carry an error field, ADV → NaN which correctly excludes). Fixed:
- **A6/S10 FIXED — crashed rolling-cointegration tests passed the stability filter.** `coint_fraction` NaN meant
  three things (history too short, worker crashed, pair never computed) and the filter kept every NaN. Worker now
  reports a status; one shared `AnalysisPipeline.coint_frac_decision` (was duplicated in analysis.py, pit_wfa.py and
  two research scripts, with a silent `getattr(..., 0.40)` default vs config 0.70) keeps NaN only for insufficient
  history and logs decision counts. Test `_verify_coint_frac_nan_status.py` 0/10 → 10/10; pit_wfa suites pass.
- **ML gate FIXED — `MLConditioner.predict_prob` returned 1.0 ("allow") on any error**, including a missing feature
  column (KeyError), so a broken Layer-2 gate silently let every entry through (NaN would too: `NaN < thr` is False).
  Now fails CLOSED (0.0), counts errors, warns once per missing feature. Test 1/3 → 3/3. Latent (Layer 2 off).
- **Surfaced (behaviour kept, now visible):** `universe_loader` reports files dropped as unreadable / without a usable
  close (`LAST_DROPPED`); `pnl_dollar` logs and records unreadable price files before falling to the next source
  (`READ_FAILURES`).
- **Open (lower impact, logged here):** `analysis._apply_research_screen_flags` (research-screen files unreadable →
  flags silently not applied); `stats._load_spread_series/_load_spread_df` (skip unreadable → try next directory);
  `stats.run_permutation_test` (unreadable portfolio file → comparison Sharpe stays default); data.py's 26 handlers
  not yet triaged.

**Checked, consistent — category 5 (constants shadowing config) in production modules.** wfa.py and portfolio_sim.py
read strategy parameters from `Config.BACKTEST`; wfa's `MIN_HALF_LIFE = 2` is a documented numerical clip. Open:
`intraday_episodic_scan.py --workers` default is a hardcoded 6 (passed explicitly as cores−2 on CachyOS).

**Compustat total return (closes the D18-adjacent asymmetry for global legs).** `trfd` verified on real data (HSBC,
Toyota, BP 2024-25: exact dividend on every ex-date, identical to price return to 2e-16 otherwise, captures HSBC's
2024-05 special dividend that `divd` omits). `research/apply_trfd_total_return.py` + `pnl_dollar` returns from
`close_total_return` (test 3/4 → 4/4). Fetch in progress (WRDS job 11); apply not yet run.

**Intraday depth — checked, consistent.** All ~1,580 1h/4h files on CachyOS start 2023-07-24..08-03: uniform
yfinance accumulation, no selection-dependent IBKR depth.

**Found while fixing:** Git-Bash/Python batch lists written on Windows carry CRLF (tar "Cannot stat ...\r"); PowerShell
5.1 `Set-Content -Encoding utf8` writes a BOM that breaks `exec` of a job file. Both caught before any effect.

**2026-10-02 — C-001 corrected (found by the first claims-registry re-derivation).** `research/durability_vs_currency_wrds.py`
reported `n` and the start date from CALENDAR ROWS, including years in which neither stock has a price: NTRS/STT
"13,373 obs since 1972" is really 10,098 overlapping days from 1985-12-03; JPM/BAC 11,741 from 1979. The EG test
itself used only valid data (p-values unchanged: 0.000046 / 0.561). PAPER.md:130-137 must be updated; the 09-27
scrutiny had marked this claim STANDS — the re-derivation rule (re-run, don't copy) is what caught it.
