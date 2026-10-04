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

**M-1 — comparison arm BUILT 2026-10-03 (design approved): `spurious_regression_risk_score(..., null="same_dates")`
next to the default count-aligned null, same partners; `debug/_verify_same_dates_null.py` (4/4, mechanical: what
reaches the EG test). Real 1h data (DD, 150 partners): count-aligned 3.33% vs same-dates 4.67% rejections -- both
near nominal; 0 DD candidates in the current 1h results, so no correction changes today. Also: DD no longer looks
trend-dominated on current data (trend R^2 0.50, 47th percentile) -- the original "DD high-risk" finding was on older
data; re-derive before citing. A first synthetic design (market random walk + stationary noise) was REJECTED: both
nulls reject 100% because a random walk and its lagged copy stay cointegrated, so rejection rates cannot separate
them in that design. Original finding:** non-like-for-like null in `trend_dominance_diagnostic.leg_corrected_pvalue`.
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

**2026-10-03 — bug recheck (T14) finds tests touching real data.** Full verify suite on CachyOS: 310/319 pass.
- `_verify_wrds_lead_lag_scan.py` wrote fake Tier 1/2 files into the REAL `output/research/` under the real discovery
  names and then **deleted** them (os.remove) — destroying any real `wrds_deep_history_episodic_scan_tier1/
  tier2_confirmed` output (both were missing on CachyOS); it also wrote fake symbols into the real WRDS cache. Now
  sandboxed in a temp directory. Real cost this time: nil (the files are regenerated by the `--fresh` discovery run).
- Audit of all 319 verify scripts for writes into real output folders: `cross_listing_lead_lag`,
  `dead_constants_comparison_arms`, `liquidity_bar_vs_symbol_comparison` wrote uniquely-named fake symbols into
  real caches and removed them afterwards (pollution while running / if they crash) — **sandboxed 2026-10-03**
  (temp dirs; all three pass; 0 files leaked);
  `manifest_pruning`, `save_tf_results_return`, `liquidity_bar_masking`, `streaming_checkpoint_results` only touch
  their own scratch folders.
- Leftover fakes from an older test version found on the Surface since 2026-08-14 (`VERIFYYF_*` in the yfinance
  cache, `VERIFYWRDS_1D` in the WRDS cache; 10 rows each, constant 100 — below every history floor) → moved to
  `output/cache/_test_leftovers_20261003/`. CachyOS clean. (`AAA`/`BBB` in the WRDS cache are REAL CRSP securities.)
- Failures classified by re-running at the pre-session commit 5f7e28b8 (same data): PRE-EXISTING
  `bug_d62_sharpe_convention`, `capital_constraint_luck_check`, `hierarchical_dsr`; INTRODUCED by intentional changes
  and updated to test the new rule: `universe_loader` (D16 labels), `full_us_market_label_map` (D17 recency),
  `save_tf_results_return` (A6/S10 — plus a new crashed-test case); `wrds_lead_lag_scan` (sandboxed above);
  `paper_claims` (reads saved outputs; under investigation — passed at 5f7e28b8 on the same files).
- **Pre-existing failures resolved (same day).** A first "before" run was invalid (the old worktree already had an
  `output/` folder, so the data link nested and data-dependent tests SKIPPED and "passed") — redone with the link in
  place: `bug_d62_sharpe_convention`, `capital_constraint_luck_check`, `hierarchical_dsr` and `paper_claims` all fail
  at 5f7e28b8 too. The first three were fixtures written for the calendar-day convention that P1 (2026-09-26)
  replaced with business days (calendar-day reference; dense fixture with weekend exits; a fixture starting on a
  Saturday) — updated, now 4/4, 11/11, 8/8. They stayed red for a week because P1 was committed without a full-suite
  run → process fix: full verify suite before committing changes to core modules (plan T14.3). `paper_claims` fails
  because PAPER.md's Act-3 numbers no longer match the saved outputs; those claims are already marked for withdrawal
  (PAPER_SCRUTINY) — resolves with the redraft (T6). Suite now: 318/319 expected green (+ `_verify_data_wrds` needs a
  live WRDS connection).

**2026-10-03 — A3 held after independent review (adversarial-reviewer; every claim below re-run by me).**
- A3 itself is correct: `_build_pair_result` fitted hedge ratios on prices forward-filled through DATA_GAP runs
  (test `debug/_verify_pair_result_hedge_gap_mask.py`: 0.665 on HEAD vs 0.700 on real rows). Real data, 24 pairs of the
  2026-08-24 1-day run: 16 hedge ratios change (e.g. OVV/PERMNO82298 0.316 → 0.753).
- **But masking exposes code-review A2** (confirmed-open): wherever the rolling hedge has no value, the spread falls
  back to the FULL-SAMPLE hedge ratio (lookahead). With A3, ATXG/KNBE (91 tradeable bars) and
  GVKEY248220_01W/GVKEY329260_01W (149) have a rolling hedge on 0 tradeable bars → 100% full-sample hedge; before A3
  the same pairs used hedges fitted on forward-filled fake prices. Both versions are wrong.
- My companion rule ("exclude if the rolling hedge is never finite") was WRONG and is withdrawn: it tested any row,
  and `ols_rolling` writes values on dead DATA_GAP rows, so it missed exactly those pairs; and it excluded every clean
  pair shorter than 60 bars (45/59/61-bar pairs excluded, 80 kept — most 6M/1Y pairs; `hr_window` floor 60 is
  hardcoded) — an undisclosed methodology change.
- Also from the review: with A3, `coint_fraction_rolling_t` changes a lot for daily pairs (`is_genuine_data_gap` is
  False for daily-or-coarser TFs, so `longest_gap_respecting_segment` joins real bars across multi-year holes:
  ALTG/FBM 0.174 → 1.000) — feeds `--storm-coint-frac` sizing and ML features. Kalman with NaN rows: OK.
  `episodic_pairs_adapter` DROPS DATA_GAP rows where the main pipeline NaN-masks them (rolling windows then span
  different calendar time).
- New finding (verified): `HedgeRatioEstimator.tls` returns the inverted slope (B on A): true 0.7 → TLS 1.429.
  Used only for reporting (`stats.py` beta_tls). Open, low.
- **Status: A3 code kept UNCOMMITTED pending Ross's decision on A2** (how the hedge ratio is estimated where the
  rolling window has no data, and on daily coint-fraction gap handling). Recommendation: a causal fallback
  (expanding-window OLS on past real rows only) replacing the full-sample hedge, built as a comparison arm first.
- **Flaky in the full suite (open):** `_verify_pit_wfa` and `_verify_pit_wfa_wrds_daily_merge_and_save` each
  failed once in a full suite run and pass alone (3/3 and 7/7 on CachyOS, also on the Surface). CORRECTION (same
  day): I first called this "parallel-run collisions" — wrong: `_run_all_verify` defaults to ONE worker, so those
  runs were sequential. Cause unknown; candidates: the live WRDS fetch writing to the cache at the same time, CPU
  load timeouts. No shared file path found; the suite logs only the FAIL line. Next: have `_run_all_verify` save the
  failing test's output.
- **B1–B4 committed 2026-10-03** (A3 held). Full suite with all changes: 317 pass; the only failures were 4 replay
  tests of legacy-only mechanics (now pinned to `pnl_mode="legacy"` explicitly, all pass), `paper_claims` (→ T6) and
  the flaky `_verify_pit_wfa`. Research scripts that relied on the legacy default now stop with a clear error
  (`capital_sim_selection_mechanism.py`, `pdr_calmar_comparison.py`, the Kelly arms of
  `parameter_sensitivity_screen.py`) — convert if re-run.
- **2026-10-03 (evening) — A2 arm, intraday dollar P&L, TLS + forex fixes committed.** Final full suite (CachyOS,
  nice 19, while the discovery scan was running): 322/326 pass; `data_wrds` (needs live WRDS), `paper_claims` (→ T6;
  passes on the Surface, whose older backtest outputs still match PAPER.md — the paper's numbers reproduce only from
  those files), and two TIMEOUTS under load: `squeeze_momentum_signal_validation` (passes alone in 80 s on the
  Surface) and `polars_universe_loader` (passed in the A2 suite at 15:43; nothing since touches the loader).
- New findings fixed today, each failing-first: TLS hedge returned 1/β (`_verify_tls_hedge_direction.py`, reporting
  only); forex "=X" tickers counted as USD in dollar P&L (`_verify_usd_symbol_fx.py`; 0 of 2,623,505 saved trades
  have a forex leg — latent).
- **Unilever ADR ratio (T1.9) — investigated 2026-10-03, still OPEN, disclosed.** UL (CRSP) / USD price per Compustat
  listing of gvkey 010846 (Unilever PLC), median by year: London 01W 1.047–1.11 (2013-2020, drifting, data ends
  2020-11-27); 02W 1.05–1.11 (ends 2019-07); Amsterdam 16W 0.948–0.953 (2018-2025, stable). Explained part: before the
  2020 unification the Amsterdam line was NV shares, and NV/PLC are the classic dual-listed twins that traded at
  different prices (Rosenthal & Young 1990) — 01W vs 16W differing by 11–14% pre-2020 is that. Unexplained: UL (one
  PLC share per ADR) drifting 5–11% above London PLC by year, and ~5% below Amsterdam PLC after 2020 when both are PLC
  shares. UL is not in the CRSP ordinary-share security master, so how its file was resolved (ticker as-of) needs
  checking next; other ADRs (HSBC, BP, Shell, AZN, Honda, Toyota, Sony) match to the share ratio, so the FX
  conversion itself is not the suspect. Effect: any pair involving these Unilever lines carries a level offset in a
  price-level spread (hedge ratio absorbs a constant, not a drift).
- **2026-10-03 (night) — T14.4 backtest fixes committed (B5, B6, B7, B10, B13, B14, B15).** Full suite on CachyOS:
  329/335; failures now carry their output (`output/verify_runs/last_failures/`): 4 TIMEOUTS under the discovery
  scan's load (`a2_causal_hedge_arm`, `absorption_ratio` pass alone in ~5 s; the two LSTM tests are TensorFlow under
  load), `paper_claims` (→ T6), and `_verify_regime_conditional_adjustment` — it ENCODED the B13 lookahead (expected an
  09:30 intraday timestamp to see that day's end-of-day row); updated to the causal expectation.
