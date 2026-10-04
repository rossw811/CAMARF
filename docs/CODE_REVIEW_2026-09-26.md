# Code Review Ledger — 2026-09-26 (Opus 5.5 audit, goal step 1)

Sequential full-file review of the core modules, one module group at a time. Every finding is
independently checked (code read + real-data measurement where the impact is empirical) before it
is marked CONFIRMED — review-agent output is treated as a lead, not a result.

Status key: **FIXED** (reproducing test failed before, passes after) · **CONFIRMED** (verified,
not yet fixed) · **CONFIRMED-LATENT** (real in code, zero measured effect on current data) ·
**KNOWN** (already disclosed elsewhere) · **UNVERIFIED** (review-agent claim, not yet checked).

Review order: ml.py+portfolio_sim.py → backtest.py → analysis.py → data.py →
stats.py+deflated_sharpe.py+pit_wfa.py → macro.py+universe_loader.py+config.py → PAPER-feeding
research/ scripts.

---

## Group 1 — ml.py + portfolio_sim.py (diff-scoped review since 4ee4d82a)

| # | File:line | Sev | Finding | Status |
|---|---|---|---|---|
| 1 | portfolio_sim.py `_reorder_for_quality_admission` | High | Quality admission re-ranked within a calendar-day bucket; step-1 settlement is irreversible shared state, so a 10:00 trade processed before a 09:00 one took capital before it existed and settled positions exiting 09:00–10:00 into the 09:00 trade's equity. | **FIXED** — re-rank only identical `entry_time`; `batch_freq` param + `--quality-admission-batch-freq` removed. `_verify_portfolio_sim.py` Case N2a/N2b failed before, pass after. Original Case N fixture asserted the lookahead as correct (09:00/10:00) — corrected. |
| 2 | portfolio_sim.py (same root cause) | High | Later-entered positions counted in earlier trade's committed capital / MTM. | **FIXED** (same fix). |
| 3 | ml.py `_train_and_validate` | Med | Youden-J threshold (maximizes balanced accuracy) judged on raw accuracy — penalized by construction under 59/41 imbalance. | **FIXED** — balanced accuracy reported for both thresholds. Re-run: 57.72% (0.5) vs 57.64% (recalibrated) — the 09-22 "doesn't help" verdict survives on the correct metric. |
| 4 | ml.py `_youden_optimal_threshold` | Low | Returns `inf` (sklearn 1.9 `thresholds[0]`) when best J ≤ 0. | **FIXED** — returns NaN; new test failed before, passes after. |

Re-run of all 12 quality-admission runs + 6 luck checks after the fix (CachyOS,
`latest_run_review_fix_rerun.log`, copies in `output/research/quality_admission_2026-09-26/`):
momentum IS 0.2337→0.1499, combined IS 0.1000→0.0357 (the lookahead did inflate them); the 09-22
luck-check "fully fixed/mostly fixed" verdicts do not survive (squeeze 99.9/93.1 pct, momentum
15.5/28.6, combined 77.9/44.5; taken_better_than_skipped False in all 6). **All of these numbers
still sit on the broken P&L accounting below (#B2–#B4) and are not final.**

Side observation (not yet investigated): `_verify_portfolio_sim.py` Case 8 prints half/full-Kelly
notional $18.7M labelled "capital-capped at ~$10M"; the check only compares the two to each other.

---

## Group 2 — backtest.py (full-file review at HEAD)

| # | Line | Sev | Finding | Status |
|---|---|---|---|---|
| B2 | 1096 | **Critical** | Gross P&L = Δ(log_a − β_t·log_b) × shares with β re-estimated every bar → includes `(β_entry − β_exit)·log_b` drift no held position earns. | **CONFIRMED on real data.** 2,062 momentum-gate 1D OLS trades, reconstruction matches stored `entry_spread` exactly: recorded gross sum **+31,865**, fixed-entry-β gross **−983**, drift term **+32,849**. Median \|drift\|/\|recorded\| = 1.00; 49% of trades flip sign; win rate 21.2% recorded vs 45.6% fixed-β. Not yet checked: Kalman, other gates, intraday; 29% of sampled trades didn't reconstruct exactly (excluded, cause unknown). Script: scratch `beta_drift_decomp.py`, output `output/research/beta_drift_decomp_2026-09-26.parquet` (CachyOS). **FIXED as default 2026-10-03** (Ross: dollar P&L everywhere): `backtest.apply_pnl_basis` re-marks every trade via pnl_dollar.py in `_run_all_pairs`, `--capital-sim`, `pit_wfa_wrds_daily`, `portfolio_sim` CLI (default pnl_mode="dollar"); unpriceable trades dropped + counted; `--legacy-pnl` = known-wrong, own `_legacypnl` label. `debug/_verify_backtest_dollar_pnl_default.py` (fails on HEAD, 7/7 now). Real data (143 1D trades): legacy +274.7 spread units vs dollar −$1,809 on 121 priced trades; 34% flip sign; 22 unpriceable. Open: intraday dollar marking; risk-based sizers (flat_2pct/Kelly) exist only in legacy. |
| B3 | 186, 1096–1112 | **Critical** | `pnl_gross` is log-units × shares; `pnl_cost` is dollars → `pnl_net` mixes units (cost overweighted ≈price× for $100 stocks, underweighted for penny stocks). | **CONFIRMED** by code (`N_SHARES_PER_TRADE=100`, `COMMISSION_PER_SHARE=$0.005`, spread in log units). **FIXED with B2 2026-10-03** (cost and gross both in dollars by default). |
| B4 | 2172 | **Critical** | `--hedge both` (default) emits near-duplicate OLS and Kalman copies of each trade; portfolio/trial registry/capital-sim treat them as independent. | **CONFIRMED** — momgate IS: 95,485 rows, 50,896 distinct (pair, tf, entry, exit). **FIXED 2026-10-03** (Ross-approved): `--hedge both` removed; default ols; `--hedge kalman` = own arm, `_kalman` output label. `debug/_verify_backtest_hedge_default.py` (fails on HEAD, 5/5 now). |
| B1 | 501 / 770 | High→Low | NaN-z rows dropped before loop, so `data_gap` force-close is dead code. | **CONFIRMED-LATENT.** Persisted 1day spread files contain zero DATA_GAP flags (only 0/1/NaN); 0 of 8,000 sampled 1D trades held across any NaN-flag/NaN-z bar. Fix as hardening. Separate open question: why no DATA_GAP flag survives into spread_series at all (NaN flags instead) — carry into analysis.py review. **FIXED 2026-10-03** (T14, Ross-approved): outage = >5 business days with no valid bar (nights/weekends never count; intraday flags mark every night DATA_GAP so flags can't be the trigger); held position exits at the first valid bar after it. `debug/_verify_backtest_data_gap_exit.py` (fails on HEAD, 6/6 now). Real data: 143 1D trades, exit reasons identical before/after (latent, as found). Limit: an intraday outage shorter than one trading day is not caught. |
| B5 | 1115 / 925 | Med | `_pair_pnl` (P&L cap state) keyed by pair only, never reset between hedge methods/TFs → with `--pnl-cap --hedge both`, Kalman pass is gated by OLS pass's full-series P&L (lookahead). | **CONFIRMED** by code (same engine, loop at 2172). Affects PAPER.md's P&L-cap variant. **FIXED 2026-10-03** (T14.4): running total per run (pair, tf, hedge) from zero; `_verify_backtest_pnl_cap_scope.py` (fails on HEAD: a 1D run's +172.82 blocked the same pair's 1h run). Also found: since B2/B3 the cap budget is dollars but the running total spread units → `--pnl-cap` now requires `--legacy-pnl`. |
| B6 | 2542 vs 2675 | Med | `--entry-z`/`--override` applied only after the IS-only fitting engine is built with raw `Config.BACKTEST`. | **CONFIRMED** by code order. **FIXED 2026-10-03** (T14.4): `_build_backtest_cfg` builds the overridden config before BOTH engines; `_verify_backtest_override_fit_engine.py`. Found while fixing: Config sections are CLASSES, so `copy.copy(Config.BACKTEST)` returned the global itself and every override mutated it process-wide — `config.section_copy` (subclass) now; engine cfg passed to dollar costs so COMMISSION/SLIPPAGE overrides still apply. `strategy_search.py` has the same copy pattern but sets all 5 varied keys every task → its results are unaffected (left unchanged: pre-registered script). CORRECTED 2026-10-04 (independent T14.7 review): that sentence was wrong -- portfolio_sim is imported lazily after the override, so STOP_ZSCORE DID see overrides before; and RegimeConditioner (REGIME_*) also read the global. Both silently lost overrides after the B6 fix (a regression); fixed: the engine hands its cfg to the regime conditioner, replay_portfolio/stop distance take stop_zscore from the run's cfg (`_verify_backtest_override_fit_engine.py` 7/7). |
| B8 | 505–510 | Med | Holdout cutoff is 80% of each pair's own bars, not a common calendar date; IS-only fitting pools across pairs → cross-pair OOS leakage into weights. | **CONFIRMED** by code. **NEEDS ROSS (2026-10-03):** fix = one common calendar holdout date across pairs; changes the holdout definition (ties to DEV-055) → decision, not a silent fix. **Ross 2026-10-04: common calendar cutoff, as a comparison arm first.** |
| B11 | 1246–1247 | Med | Portfolio Sharpe: calendar-day resample (weekends = 0) × √252; P&L booked at exit, not MTM. Feeds `record_trial` → DSR. | **CONFIRMED** by code. **→ FIXED** (commit 85e766fb (P1 business-day P&L); reconciled 2026-10-03) |
| B12 | 368–378 | Med | `MLConditioner.predict_prob` returns 1.0 on any exception; `fillna(0.0)` on missing features. Layer 2 can silently become Layer 1. | **CONFIRMED** by code. (Layer 2 disabled by default.) **→ FIXED** (commit 516c9a10 (fails closed; _verify_ml_gate_fail_closed.py); reconciled 2026-10-03) |
| B15 | 2162 | Low | Survivorship truncation compares against `spread_df.index.max()` (shared index end), not the symbol's last real bar. | **CONFIRMED** by code; impact limited (post-delist bars are NaN → dropped). **FIXED 2026-10-03** (T14.4): `data_last_seen` = last bar with a finite spread; `_verify_survivorship_last_real_bar.py`. |
| B9 | 974 | Med | Same-bar fill. | **KNOWN** — `research/fill_timing_sensitivity.py` (Development.md ~9841, PAPER.md ~2264). But that study's result (mean Sharpe 26.957 vs 26.468) was computed on the B2/B3 P&L and must be re-run after the fix. Re-run `research/fill_timing_sensitivity.py` on dollar P&L (B2/B3 now default) — open. |
| B7 | 2525 / 1560 | Med | No lookahead warning for `--decay-rate-sizing` with `--holdout`; weights come from precomputed `output/research/decay_rate_at_entry_detail.parquet`, same shape as the warned regime-age case. | **CONFIRMED** by code. **FIXED 2026-10-03** (T14.4): warning for --decay-rate-sizing/--decay-rate-modifier with --holdout, and every such holdout run (incl. --regime-age-sizing) is labelled `_lookaheadrisk`; `_verify_backtest_lookahead_label.py`. |
| B10 | 559 | Med | Liquidity bar filter reindexes a daily mask onto the bar index with `fill_value=False`. | **CONFIRMED, broader than reported:** `liquid_bar_mask` reads only the yfinance cache (`{sym}_1day.parquet`); WRDS-universe symbols (`output/cache/wrds/{sym}_1D.parquet`) get an empty mask → every entry blocked, at 1D too, not just intraday. Any `--storm-liquidity-bar-filter` result on the Purity pool is invalid. **FIXED 2026-10-03** (T14.4): WRDS-first source, USD price (close_usd for Compustat), each bar mapped to its own day (`mask_on_bars`; exact reindex blocked every intraday bar); `_verify_liquid_bar_mask_sources.py`. Real 1D pairs with the filter on: 11 trades (old) → 75 of 143 (new). |
| B13 | 272 | Low | Regime lookup matches same-day EOD macro row for intraday entries. | **CONFIRMED** by code (Layer 2 only, disabled by default). **FIXED 2026-10-03** (T14.4): intraday entries see macro rows strictly before their date; `_verify_regime_lookup_intraday.py`. |
| B14 | 1414 | Low | Hub weights read `output/results/*/pairs.parquet`, ignore `--pairs-override`. | **CONFIRMED** by code. Affects PAPER.md's hub-weight variant. **FIXED 2026-10-03** (T14.4): `compute_hub_weights(..., pairs_df=_pairs_override_df)`; `_verify_hub_weights_override.py`. |

**Blocking decision (awaiting Ross):** B2/B3/B4 contaminate every P&L-derived number (Sharpe, DSR,
capital-sim, quality-admission, luck check, PAPER.md headline tables). Proposed: rebuild P&L in
dollars from leg prices with shares fixed at entry (`n_b = β_e·n_a·P_a/P_b`), dollar costs from leg
notionals, built as `pnl_dollar_*` comparison columns first; report hedge methods separately, never
pooled; adversarial-reviewer pass + decomposition across Kalman/all gates/intraday before any
PAPER.md edit. ML labels (z-based convergence) believed unaffected — to be verified, not assumed.

---

## Group 3 — analysis.py (full-file review at HEAD)

| # | Line | Sev | Finding | Status |
|---|---|---|---|---|
| A1 | 1718 (+1853, 2155, 4424, 5620) | **Critical** | `_eg_worker` masks `isfinite(log_p_a) & isfinite(log_p_b)` on per-symbol arrays of different lengths (`align_daily` trims each asset to its own first valid date) → `ValueError`, pair silently returned `ok=False`. Equal-length-but-offset intraday arrays misalign silently. | **CONFIRMED on real data, production path:** `DataAligner.align_universe` on real AAPL (11,470 bars) / MSFT (10,144) / ABNB (1,385) → `_eg_worker` raises the broadcast error for AAPL/MSFT and AAPL/ABNB. Any two symbols with different history start dates are never EG-tested in analysis.py's main pipeline. Plausibly explains the standard screen confirming only 3 pairs. `universe_loader.py:318–330` documents this exact failure and fixes it for the full-universe path by reindexing, but wrongly states DataAligner guarantees a shared calendar. Failed pairs are also silently excluded from BH's m (`n_tested = len(combined)`, analysis.py ~2104) and no failure count is logged. Corroboration: the latest standard run (`latest_run_analysis.log`, 2026-08-23, 1,658 assets) confirmed **0 pairs at 1D** and 2 total. Not yet checked: whether the episodic/pit_wfa path (source of the Purity pool) is affected — carry into group 5. **→ FIXED** (see post-review updates; reconciled 2026-10-03) |
| A2 | 2892 | High→Low | Warm-up bars use full-sample static OLS β (lookahead) while `z_rolling` is already finite. | **CONFIRMED-LATENT:** 4 of 24,047 real 1D OLS momentum-gate trades (0.02%) entered on a static-β bar. Fix as hardening. |
| A3 | 5620 | High | `_build_pair_result` builds `log_a/log_b` from raw forward-filled `close`, not `clean_close` → rolling β/Kalman/coint-fraction computed across DATA_GAP bars. | UNVERIFIED (note B1: persisted files contain no DATA_GAP flags at all — related, needs one investigation) **CONFIRMED 2026-10-03, fix HELD** (independent review): masking is correct but exposes A2 (full-sample hedge fallback) — see INCONSISTENCY_SWEEP 2026-10-03; awaits Ross's A2 decision. |
| A4 | 3106 | Med | `mean_window` derived from full-sample half-life → "causal" z_rolling window depends on future bars. | UNVERIFIED |
| A5 | 6190 | High | Secondary-evidence override uses dense-grid `n_bars`; ZA/CUSUM return None on short real series, read as "no break". | UNVERIFIED |
| A6 | 6285 | Med | NaN `coint_fraction_rolling` pairs pass the episodic filter unchecked; window sized off the first pair. | **CONFIRMED + FIXED 2026-09-28** (shared coint_frac_decision) |
| A7 | 4159 | Med | Andrews sup-F: 8.85 critical value (1 param) applied to F=W/2 with 2 params; break date off by one. | UNVERIFIED |
| A8 | 4195 | Low | CUSUM pointwise ±2√t band → near-certain crossing on long series (LIL). | UNVERIFIED |
| A9 | 735 | Med | `build_returns_matrix` right-aligns by position; intraday series ending at different timestamps are offset. | UNVERIFIED |
| A10 | 6067 | Med-High | Deep-history enrichment: `deep_aligned` keyed by symbol, overwritten across pairs → positional misalignment; WRDS/IBKR splice without level reconciliation. | UNVERIFIED |
| A11 | 4424 | Med-Low | Johansen joins across gaps (BUG-D77 fix not applied); significance param ignored (always 5% column). | UNVERIFIED |
| A12 | 2522 | Med-Low | Gold tier: residual EG at raw p<0.05, no FDR, one direction only. | UNVERIFIED |
| A13 | 2458 | Low-Med | Factor returns from raw returns on correlation eigenvectors; scale drifts with coverage. | UNVERIFIED |
| A14 | 5263 | Med-Low | ADV filter uses full-history mean dollar volume (lookahead/survivorship, undisclosed). | UNVERIFIED |

---

## Group 4 — data.py (full-file review at HEAD)

Explains the B1 puzzle (no DATA_GAP flags in persisted spread files): gaps are forward-filled at
cache time (D1, D8) before alignment sees them, 4h overnight gaps fall under the 5-bar FILL limit
(D5), and the intraday OOM guard flags everything NONE (D7).

| # | Line | Sev | Finding | Status |
|---|---|---|---|---|
| D1 | 1874 / 2198 | **Critical — FIXED 2026-09-26 (code); cache re-fetch pending** | `_liquidity_filter` NaNs prices on bars under $1M dollar volume, then forward-fills; flagged NONE downstream. Every ticker passed as asset class "equity", so forex (volume 0) is wiped. | **CONFIRMED on real cache:** EUR.USD / GBP.USD / AUD.USD 1day = 100% NaN close. Across 1,697 yfinance 1day files, median zero-change-close fraction 9.4%; 573 files >20%, 82 files >50% — fake flat bars entering correlation/EG/ML as clean data. Not yet checked: WRDS cache (`output/cache/wrds/`) — if it bypasses `_liquidity_filter`, the Purity pool is less exposed. **→ FIXED** (see post-review updates; reconciled 2026-10-03) |
| D2 | 2136 / 2107 / 5101 | High | Daily incremental refresh never runs (freshness check inverted), would be rejected by MIN_BARS and would overwrite full cache if it did; logs "updated" anyway. | **CONFIRMED on real cache:** 227 of 300 yfinance 1day files end 2026-06-17 (DataAligner run earlier today also reported range ending 2026-06-17). **→ FIXED** (see post-review updates; reconciled 2026-10-03) |
| D3 | 1625 | High (lookahead) | 4h `snap_timestamps` allows one bar/session; 13:30 bar overwrites 9:30. | **CONFIRMED (repro):** 2 bars in → 1 out, stamped 09:30 carrying the 13:30 bar's close — a 4h lookahead on every 4h bar from IBKR / yfinance-fallback paths. **→ FIXED** (see post-review updates; reconciled 2026-10-03) |
| D4 | 1621 | High (lookahead + loss) | Banker's rounding collides on-the-hour IBKR bars; yfinance 15:30 bar clamped onto 14:30. | **CONFIRMED (repro):** IBKR 1h 6 → 4 bars (11:00, 13:00 lost); yfinance 1h 7 → 6 bars with 14:30 stamp carrying the 15:30 close (up to 90 min lookahead). Feeds primary 1h cache and 4h resample. **→ FIXED** (see post-review updates; reconciled 2026-10-03) |
| D5 | 1298 | High | 4h weeknight gap = 4 bars ≤ `_MAX_FILL_BARS` → FILL, forward-filled into EG/corr (inflates n and ADF significance). | UNVERIFIED (reviewer repro: 32/68 rows fake FILL) **→ FIXED** (see post-review updates; reconciled 2026-10-03) |
| D6 | 1171 | Med | `align_daily` >50% gap exclusion measured after ffill → never fires; SPARSE never set. | UNVERIFIED |
| D7 | 1269 | Med | Intraday OOM guard returns raw index with all flags NONE. | **CONFIRMED + FIXED 2026-09-27** (round 3) |
| D8 | 1835 | Med | Cache-time ffill of IBKR daily; `tf_ibkr=tf_label` disables MAX_MISSING_PCT for non-IBKR sources. | **CONFIRMED + FIXED 2026-09-27** (round 3) |
| D9 | 1856 | Med | `_roll_adjust` treats any >5% move as a roll, flattening real futures moves. | **CONFIRMED + FIXED 2026-09-27** (round 3) |
| D10 | 3209 | Med | Raw unsnapped extended-hours IBKR bars written to cache before snapping. | **CONFIRMED + FIXED 2026-09-27** (round 3) |
| D11 | 1789 | High | `_standardize` drops tz without converting to ET; yfinance crypto intraday stored as UTC clock time. | UNVERIFIED |
| D12 | 456 | Med | Split reconciliation compares different dates; dividend seams never reconciled. | **CONFIRMED + FIXED 2026-09-27** (round 3) |
| D13 | 1976 | Med (lookahead) | 1M/3M/6M bars stamped period-start with period-end close. | **CONFIRMED + FIXED 2026-09-27** (round 3) |
| D14 | 5738 | Med | Wikipedia S&P 500 result cached without size check (violates CLAUDE.md "never cache empty"). | **CONFIRMED** by code (`_save_sp500_cache(tickers)` directly after parse, no length guard). **→ FIXED** (see post-review updates; reconciled 2026-10-03) |
| D15 | 2443 | Low | `_attempts[0][0]` compares first character; working period always cached and pinned. | **CONFIRMED** by code (`_attempts` is a list of period strings, line 2321). **→ FIXED** (see post-review updates; reconciled 2026-10-03) |

Confirmed intact: universe-size guard (line 3964); `_fetch_constituents_cached` refuses empty.

D1 follow-up (WRDS cache, CachyOS, 1,500 random `output/cache/wrds/*_1D.parquet`): median
zero-change-close fraction 14.3%, 454/1,310 readable files >20%, 15 >50%. NOT yet attributable to
D1 — `data_wrds.py` does not call `_liquidity_filter` directly, and thin international listings have
genuine flat days. Next check: volume on zero-change bars (0 ⇒ fill, >0 ⇒ genuine).
**New finding D16:** 1,647 of 59,021 WRDS cache files are 0 bytes (31/1,500 in the sample were
unreadable). Every loader must be checked for silent drop vs crash on these — carry into the
universe_loader.py review (group 6).

---

## Group 5 — stats.py + deflated_sharpe.py + pit_wfa.py (full-file review at HEAD, plus callees)

**A1 exposure of the Purity pool: NOT affected.** Purity comes from `research/episodic_pairs_adapter.py`
reading Tier-3 per-window p-values from `wrds_deep_history_episodic_scan.py` /
`intraday_episodic_scan.py`, which build one union-indexed frame and apply a joint isfinite mask
per pair — `_eg_worker` gets equal-length, date-aligned arrays there. `pit_wfa.py`'s own screen IS
affected (S1). DSR formula itself verified correct by the reviewer (SR0, (kurt−1)/4 with
non-excess kurtosis, √(T−1), per-period units).

| # | Line | Sev | Finding | Status |
|---|---|---|---|---|
| S3 | episodic_pairs_adapter.py:299, :443 | **Critical (honesty)** | `as_of_date` defaults to now and `main()` never passes one → Purity pairs are the union of every window confirmed up to the BUILD date, then backtested across their full history incl. the "OOS" 20%. Pair-level selection lookahead. | **CONFIRMED** by code. PAPER.md §7.20 (line ~2663) labels Purity "Genuinely PIT-safe" — an overclaim: each window is PIT-safe, the pair set is not relative to the backtest's trading dates. Bias direction is upward, so Purity's negative Sharpe is conservative; the positive squeeze/momentum-gate results on the same pool are not protected. |
| S5 | stats.py:1054 | **High** | Circular block bootstrap "Reality Check" resamples raw daily P&L without demeaning → null centered on realized Sharpe → p≈0.5 regardless of skill. | **CONFIRMED** by code; reviewer simulation: skill-less median p=0.503, Sharpe-6.1 data p=0.498. PAPER.md line 458 reports "IS p=0.559; OOS p=0.546" under a White (2000) citation — the reported numbers are exactly the bug's signature, and the method is not White's RC (no best-of-N, no demeaning). Citation-misapplication item for step 4. |
| S7 | stats.py:1184 | Med | Zivot-Andrews tuple indices swapped (statsmodels returns `(stat, p, cv, baselag, bpidx)`); `hl_za_breakdate` is the lag count's position. Inline comment asserts the wrong order. | **CONFIRMED** by code vs statsmodels signature; reviewer repro r[3]=3 lags, r[4]=149 break. **→ FIXED** (see post-review updates; reconciled 2026-10-03) |
| S1 | pit_wfa.py:259 / :288 | High | `screen_universe_at_cutoff` → `align_universe` default → per-symbol intraday grids of different spans → A1 broadcast error / silent time-shift. | UNVERIFIED (same mechanism as confirmed A1) |
| S2 | analysis.py:2048; wrds_deep_history_episodic_scan.py:898/968 | Med | Failed / one-direction-only EG tests dropped before BH → m undercounted (confirmed for analysis.py path, see A1). | Partly CONFIRMED (analysis.py path); episodic path UNVERIFIED **→ FIXED** (commit 8bb2bf0a: BH denominator keeps crashed tests; _verify_eg_bh_denominator.py; reconciled 2026-10-03) |
| S4 | pit_wfa.py:409 | Med | BUG-D69 override leaves full train+test `hedge_ratio_ols`/`hedge_ratio_kalman_mean`; backtest uses them to skip pairs and as NaN fallback. | UNVERIFIED |
| S6 | stats.py:270 / :263 | Med | Phillips-Ouliaris proxy = PhillipsPerron on estimated residuals with univariate DF critical values (reviewer sim: 25.7% rejection at nominal 10% on independent random walks); KPSS same issue (needs Shin 1994). Inflates gold/silver tiers. `arch.unitroot.cointegration.phillips_ouliaris` available. | UNVERIFIED (reviewer ran simulation) |
| S8 | stats.py:1153 | Med | AR(1)/ZA on overlapping, forward-filled `half_life_rolling` → ρ≈1 by construction; `hl_stationary` not inferential. | UNVERIFIED |
| S9 | stats.py:601 | Med | `_build_daily_pnl` groups by exit date without zero-filling (BUG-D62/D64 class) → Phase 3 pooled Sharpe inflated. | UNVERIFIED |
| S10 | pit_wfa.py:305 | Med | NaN `coint_fraction_rolling` auto-passes the MIN_COINT_FRAC gate (same class as A6). | **CONFIRMED + FIXED 2026-09-28** (shared coint_frac_decision) |
| S11 | deflated_sharpe.py:173/230 | Med | N and Var[SR] count only backtest.py trials; pit_wfa folds (`pit_wfa_portfolio.parquet` doesn't match `portfolio_*`), capital-sim and research variants never recorded; DSR never computed for the capital-sim headline. | UNVERIFIED |
| S12 | deflated_sharpe.py:244 | Low | Append-only registry counts identical reruns as trials; pools IS and holdout Sharpes. | UNVERIFIED |
| S13 | stats.py:821/839 | Low | Phase 2 bootstrap annualizes per-trade P&L with √252. | UNVERIFIED |
| S14 | pit_wfa.py:252/389 | Low | `train_end == test_start`, both inclusive; no embargo. | UNVERIFIED |

**D16 corrected (group-6 cross-check):** the 1,647 zero-byte WRDS files exist **only on CachyOS**
(Surface: 0 of 59,021). All 200 checked are intact locally. mtimes cluster on two copy events
(737 on 2026-07-27, 909 on 2026-08-13, 1 on 2026-08-20) → truncated transfers. `universe_loader`'s
`_read_one` catches read errors and returns None with no count/log, so **every universe-level
CachyOS run since mid-August has silently used ~2.8% fewer WRDS symbols than the Surface.** The
2026-09-21 parity check ("558/558 in sync") evidently did not cover `output/cache/wrds`.

---

## Group 6 — macro.py + universe_loader.py + config.py (full-file review at HEAD)

| # | Line | Sev | Finding | Status |
|---|---|---|---|---|
| U1 | universe_loader.py:137–139, 474–563 | High | WRDS/Binance/IBKR cache dirs are relative (yfinance absolute) → run outside project root silently loads only ~1,700 yfinance symbols; memo caches the shrunken result. No universe-size guard in `load_full_universe`; unreadable files dropped uncounted (see D16 — this is the mechanism that hid the CachyOS truncation). | Unreadable-drop **CONFIRMED** (via D16); relative-path part UNVERIFIED **→ FIXED** (commit 0189deaf; reconciled 2026-10-03) |
| U2 | universe_loader.py:366–367, 382–384 | High (intraday) | `tz_localize(None)` without conversion: Binance 1h stays UTC, IBKR/yfinance 1h ET, stamped :00 vs :30 → crypto–equity intraday pairs have zero or misaligned overlap. (Same class as D11.) | UNVERIFIED (reviewer inspected real stamps) **→ FIXED** (see post-review updates; reconciled 2026-10-03) |
| U3 | universe_loader.py:373–386 | Med-High | Canonical index includes Binance weekend rows → weekday-only symbols get NaN weekends → `np.diff` log-price returns make every Monday/post-holiday return NaN (~20% of equity returns incl. weekend-news moves) in every correlation, even equity-vs-equity. No `gap_flag` column on this path, so GapFlag masking does nothing here. | UNVERIFIED |
| U4 | universe_loader.py:478–486, 537–544 | Med | Mixed adjustment: WRDS `close` is split-adjusted price-only; `close_total_return` never read; yfinance `close` is dividend-adjusted. | **CONFIRMED on real cache:** AAPL 2020-08-27 WRDS close 125.01, WRDS TR 158.52, yfinance 121.26. CLAUDE.md's "WRDS/CRSP … total-return-adjusted" does not describe what the loader uses — doc-consistency item for step 4. **→ FIXED** (see post-review updates; reconciled 2026-10-03) |
| U5 | universe_loader.py:166, 543–544 | Med | IBKR "1D" overrides WRDS daily for 90 symbols (the previously confirmed-pair set) → selection-dependent deeper history (e.g. 7267.T from 2000 vs 2023). | UNVERIFIED |
| U6 | universe_loader.py:196–208 | Med | Memo key excludes loader code version; stale memos survive code fixes; never cleaned (Surface: 20 GB across 50 pickles in `output/cache/_universe_loader_memo`). | UNVERIFIED |
| M7 | macro.py:549–552, 608–618 | High (PIT) | Lags documented as "from reference-period end" but added to FRED's start-of-month stamp → CPI (+15d) visible ~4 weeks early; FEDFUNDS (+5d) visible before its month ends. Should be ~45d / ~33d. | **CONFIRMED** by code. **→ FIXED** (commit e6b728e9; reconciled 2026-10-03) |
| M8 | macro.py:484, 824 | High (PIT) | COT indexed on Tuesday as-of date; published Friday → 3 days early. | **CONFIRMED + FIXED 2026-09-27** (round 3) |
| M9 | macro.py:604–605 + backtest.py:270 | Med-High | Daily FRED series unlagged; same-day VIX close (16:15 ET) used at day-t entry; DTWEXBGS weekly (up to ~1 week leak). Overlaps B13. | **CONFIRMED + FIXED 2026-09-27** (round 3) |
| M10 | macro.py:560, 265–276 | Med | USREC 120-day shift < real NBER lags (4–15+ months); latest-vintage backfill. | UNVERIFIED |
| M11 | macro.py:279–297, 761–771 | Med | Sahm from latest-vintage UNRATE (annual seasonal revisions); no ALFRED vintages; docstring claims live-knowable. | UNVERIFIED |
| M12 | macro.py:604–605 | Low-Med | Daily series ffilled to today with no limit/staleness flag. | UNVERIFIED |
| C13 | config.py:145–183 + data.py:1732 | High | `MIN_BARS_REQUIRED` lacks 3M/6M/1Y (all in `WRDS_PRIMARY_TFS`) → `.get(tf, 100)` demands 25/50/100 years → nearly every symbol rejected at those TFs. Same bug previously fixed in `MIN_OVERLAP_BY_TF`. | **CONFIRMED** by code. **→ FIXED** (see post-review updates; reconciled 2026-10-03) |
| C14 | config.py:610–617, 1083–1088 | Low-Med | Comments call `OU_ZSCORE_ENTRY`=2.0 / `ResearchConfig.ENTRY_Z`=2.0 "production"; actual `BacktestConfig.ENTRY_ZSCORE`=3.0. | **CONFIRMED + FIXED 2026-09-27** (round 3) |
| C15 | config.py:785–787 + backtest.py:315–321 | Low | `REGIME_SIZING` comments disagree with code (1.5x/1.0x, not normal/0). Latent (Layer 2 off). | **CONFIRMED + FIXED 2026-09-27** (round 3) |
| C16 | universe_loader.py:131 | Low | `_IO_WORKERS = 32` hardcoded (project rule: derive from `os.cpu_count()`). | **CONFIRMED + FIXED 2026-09-27** (round 3) |

---

## Core-module review complete (groups 1–6). Next: PAPER-feeding research/ scripts.

---

## Group 7 — research/ scripts feeding PAPER.md (55 cited; reviewed in claim-ordered batches)

### Batch R1 — the Purity-pool pipeline
`wrds_deep_history_episodic_scan.py`, `intraday_episodic_scan.py`, `episodic_pairs_adapter.py`,
`build_comparison_arm_pairs.py`, `pit_wfa_wrds_daily.py`, `bh_vs_by_full_universe_1d.py`.

Independently recomputed from `output/research/wrds_deep_history_episodic_scan_tier3_windows.parquet`
(2026-09-02; 5,003,637 pair-windows): **1,699** BH-rejected windows → **929** confirmed pairs, of
which **750 (81%) rest on exactly one window** despite 90% overlap between adjacent windows
(2,520-bar window, 252-bar step). BH over all pair-windows is correctly scoped (m right), but
collapsing any-of-K windows to pairs bounds the pair-level FDR at 0.05·1,699/929 = **9.1%**, not 5%.
**498 of 929** have a GVKEY (Compustat Global) leg. Note: local `purity_pairs.parquet` is the
2026-08-12 182-pair build; the 1,375-pair pool used since 09-21 exists only on CachyOS.

| # | Line | Sev | Finding | Status |
|---|---|---|---|---|
| R1.1 | episodic_pairs_adapter.py:157; data_wrds.py:1300 | **Critical** | Compustat Global prices are `prccd/ajexdi` in local currency, no FX conversion (FX table exists at data_wrds.py:1331–1363, never applied). Cross-currency pairs test cointegration without FX; P&L sums JPY/HKD/… with USD. | **CONFIRMED:** 7267.T (Honda) close 1,536 (JPY); 498/929 confirmed pairs have a GVKEY leg. Explains the $1,000 median leg price in the B2 decomposition sample. **→ FIXED** (commits 5f7e28b8 + 0c1d1a43 (FX applied to 15,093 listings) + 3c6d8720 (ADR check); reconciled 2026-10-03) |
| R1.2 | wrds_deep_history_episodic_scan.py:745–751 | High | ADV gate multiplies local-currency price by volume vs a USD threshold → JPY listings overstated ~150× → gate effectively off for all GVKEY symbols. | UNVERIFIED (follows directly from R1.1) |
| R1.3 | wrds_deep_history_episodic_scan.py:737 | Med | S&P 500 membership gate applied only when both legs map to a permno → GVKEY–GVKEY pairs (446k of 638k tested) skip it; pool tilts international. | UNVERIFIED |
| R1.4 | episodic_pairs_adapter.py:154 | Med | Discovery on CRSP `close_total_return`; traded spread/gating built from yfinance adjusted (tickers) or WRDS price-only `close` (PERMNO) → hedge ratio / half-life traded ≠ tested. (Same family as U4.) | UNVERIFIED |
| R1.5 | wrds_deep_history_episodic_scan.py:184; data_wrds.py:327/515 | Med | `close_total_return` built with `dlyret.fillna(0.0)` → missing days become flat carried prices, invisible to the isfinite mask (GapFlag rule). "Split-only = 2 symbols" docstring stale (actually 15,094). | UNVERIFIED |
| R1.6 | wrds_deep_history_episodic_scan.py:1033 | Med | `min_windows_confirmed=1` → pair-level FDR not controlled at α. | **CONFIRMED** (numbers above) |
| R1.7 | wrds_deep_history_episodic_scan.py:1343 / 1186 | Med | Checkpoint cleared before BH step and before the windows file is saved → OOM there loses days of Tier-3 work. | UNVERIFIED |
| R1.8 | wrds_deep_history_episodic_scan.py:1156/1264/1306/938 | Med | Resume caches not keyed on universe/params; tier3 checkpoint resumes by count, stale parts concatenated. | UNVERIFIED |
| R1.9 | intraday_episodic_scan.py:203 | Med | Output/checkpoint paths omit `--window-config`/`--tier3-threshold` → silent reuse across configs. | UNVERIFIED |
| R1.10 | intraday_episodic_scan.py:136–142, 160, 277 | Med | Universe from Step-0 coverage file (~1,576 current constituents), not `load_full_universe` (standing rule; survivorship); no ADV/membership gate; `workers=6` hardcoded. | UNVERIFIED |
| R1.11 | bh_vs_by_full_universe_1d.py:129, 87 | Med | One-direction EG (production uses max of both) → BH-vs-BY counts from a less conservative family than cited; price-only/local-currency closes. | UNVERIFIED |
| R1.12 | pit_wfa_wrds_daily.py:387 | Med | `load_full_universe(columns=["close"])` → split-only US + local-currency GVKEY; mismatches the total-return discovery series. | UNVERIFIED |
| R1.13 | pit_wfa_wrds_daily.py:269–276 | Low | Hedge ratios from train+test fit used as backtest skip gate (same as S4). | UNVERIFIED |
| R1.14 | episodic_pairs_adapter.py:309–330 | Low | Resume filter ignores as_of/alpha; `--alpha 0.01` without `--out-suffix` overwrites production output. | UNVERIFIED |
| R1.15 | build_comparison_arm_pairs.py:108; adapter:217 | Low | Ordered-key matching (A,B) vs (B,A) — latent (zero overlap today); `write_spread_series` overwrites standard-screen files despite docstring. | UNVERIFIED |

### Batch R2 — statistical-evidence scripts
`capital_constraint_luck_check.py`, `hierarchical_dsr.py`, `parameter_sensitivity_screen.py`,
`squeeze_momentum_features.py`, `capital_size_sweep.py`, `lstm_attention_training.py`.
Clean per reviewer: luck-check anti-join key unique (with `n_shares_b`); squeeze/RSI features use
trailing windows only.

| # | Line | Sev | Finding | Status |
|---|---|---|---|---|
| R2.1 | hierarchical_dsr.py:132–142 | **High** | Merged registries never de-duplicated. | **CONFIRMED on real files:** local 437 + CachyOS 713 = 1,150 records, **570 unique** (records identical incl. `timestamp_run` — CachyOS registry contains copies of local). Inflates N and every n_family, shrinks Var[SR] via repeated identical Sharpes. The 09-21 family DSR (squeeze/momentum 0.9676) and pooled DSR are computed on this. Line 206's "matches deflated_sharpe.py exactly" is false (1,150 vs 990). |
| R2.2 | parameter_sensitivity_screen.py:101–103 | High | `corr_exit_window` sweep is a no-op. | **KNOWN** (HANDOFF 2026-09-21, "dead-config bug"). **New part, CONFIRMED by code:** the 60 no-op runs still form their own `sens_corr_exit_window` family in hierarchical_dsr.py:80, and the overfitting guard's `idxmax` tie-break reports rank 1 / `overfit_risk=False` for a parameter with zero effect. |
| R2.3 | lstm_attention_training.py:140–145 **and ml.py** | **High** | Chronological 60/20/20 split by row position, no purging/embargo, while labels look forward `RESOLUTION_BARS_MULT·hl` bars and hundreds of pairs share dates. | **CONFIRMED** by code in both `lstm_attention_training.py` and `ml.py` (no purge/embargo anywhere). So the 09-22 AUC figures (XGBoost 0.6075, LSTM 0.5897, attention 0.5516) — the basis of the FINDINGS #72 "AUC correction" — are not clean out-of-sample. Must be re-derived with purged/embargoed CV (López de Prado, AFML ch. 7) before any step-3 ML comparison. |
| R2.4 | hierarchical_dsr.py:221–223 | Med | "Best" trial chosen by registry Sharpe, SR_hat computed from whatever trades file currently has that label (labels reused up to 60×; CachyOS trials have no local file). | UNVERIFIED |
| R2.5 | hierarchical_dsr.py:165–173, 220 | Med | Var[SR] pools IS + holdout and capsim (`actual_pnl`) with per-pair portfolio Sharpes; capsim SR_hat uses original-size `pnl_net`. | UNVERIFIED |
| R2.6 | capital_constraint_luck_check.py:136 | Med | Random same-size null ignores timing/concurrency; a constraint-respecting null would replay random admission orders through the same capital sim. | UNVERIFIED (methodology — needs Ross) |
| R2.7 | capital_constraint_luck_check.py:88–100 | Med | Taken (~400) vs skipped (~95k) compared on Sharpe → diversification makes skipped look better; `taken_better_than_skipped` biased False. Mean P&L is the fair comparison. | UNVERIFIED |
| R2.8 | squeeze_momentum_features.py:110–111 | Med | RSI velocity `shift(5)` applied after reindex to 24/7 forward-filled spread index → not 5 real bars (SPY/VOO 1h: RSI coverage 17%, velocity 2.8%). | UNVERIFIED |
| R2.9 | lstm_attention_training.py:113–117 | Med | Intraday sequences = last N rows of forward-filled 24/7 spread index → mostly repeated padding (GapFlag rule). | UNVERIFIED |
| R2.10 | parameter_sensitivity_screen.py:116–118 | Low | `flat_risk_pct` sweep: 9–14 taken trades of 158,963; IS-best named with no min-n check. | UNVERIFIED |
| R2.11 | lstm_attention_training.py:164, 172 | Low | Balanced sample weights, then raw accuracy vs majority baseline → "does not beat baseline" near-guaranteed (same class as group-1 #3). | UNVERIFIED |
| R2.12 | capital_constraint_luck_check.py:139–146 | Low | NaN taken Sharpe → percentile 0 → prints a false "NOT a clear outlier" verdict. | UNVERIFIED |
| R2.13 | capital_size_sweep.py:94, 141 | Low | Output names omit `--pairs-override` → a second pool's sweep overwrites the first. | UNVERIFIED |

### Batch R3 — crisis-regime claim family (PAPER.md §5 / FINDINGS #43)
`crisis_regime_correlation_diagnostic.py`, `crisis_regime_concentration_significance_test.py`,
`crisis_regime_episode_clustering_check.py`, `crisis_regime_survivorship_confound_test.py`,
`crisis_regime_same_sector_test.py`, `crisis_regime_credit_proxy_comparison.py`.
(Reviewer line numbers for the correlation diagnostic were off — file is 330 lines; locations below
re-pinned where verified.)

| # | Line | Sev | Finding | Status |
|---|---|---|---|---|
| R3.1 | crisis_regime_correlation_diagnostic.py:191 | **High** | "Reappears" coded as any later window with regime ≠ first regime; docstring (line 46) says "later non-crisis window". Crisis is rare, so crisis-first pairs almost trivially reappear "in a different regime"; calm-first must wait for calm to end. The 91.0% vs 78.7% persistence gap (FINDINGS #43 "persistence survives") is partly base-rate asymmetry. | **CONFIRMED** by code (line 191 vs 46). |
| R3.7 | crisis_regime_same_sector_test.py:134–145 | **High (integrity)** | Right-censoring filter drops only crisis-first pairs after 2022-06-01 and keeps all non-crisis pairs regardless of date (equally censored) → biases toward crisis > calm. Comment states it was added after the first run gave the opposite, significant result. Date hardcoded; `censor_cutoff` computed and unused. | **CONFIRMED** by code, incl. the comment. Outcome-informed asymmetric exclusion — must be disclosed in PAPER.md or the test re-run with symmetric censoring. |
| R3.2 | correlation_diagnostic (confirmation) | Med-High | "Confirmed in ≥1 window" ignores exposure: crisis-first pairs average 9.52 windows tested vs 7.34 calm-first; confirmation rate rises ~7× with window count. Needs stratification / per-window rate. | UNVERIFIED (reviewer computed from real 638,095-pair output) |
| R3.3 | concentration_significance_test.py:78–82 | Med | "Exact" binomial tests the top-2 episodes selected by the same counts (post-hoc) → p=0.000006 overstated. | UNVERIFIED |
| R3.4 | concentration_significance_test.py:106–110 | Med | Nulls assume 29 confirmations independent; shared legs within episodes cluster them → rejection shows non-independence, not "something unusual happened". | UNVERIFIED |
| R3.5 | episode_clustering_check.py:115–134 | Med | Docstring promises episode-level crisis-vs-calm check; script prints crisis-only tables, no test. | UNVERIFIED |
| R3.6 | episode_clustering_check.py:141–147 | Low | Gap-rule sensitivity has no null per gap; top-2 share rises mechanically. | UNVERIFIED |
| R3.8 | same_sector_test.py:62, 112 | Med | Sectors from current Wikipedia GICS (not PIT: 2018 Communication Services, 2023 V/MA moves); tagged subset = current S&P 1500 survivors. | UNVERIFIED |
| R3.9 | same_sector_test.py:71–98 | Low-Med | No interaction test; "similar in both subsets" inferred from one significant and one non-significant test (n=75). | UNVERIFIED |
| R3.10 | survivorship_confound_test.py:232–241 | Med | Never filters to `first_regime == "crisis"` — z=1.26, p=0.21 is for all regimes. | UNVERIFIED |
| R3.11 | survivorship_confound_test.py:193–211 | Med-High | Design cannot detect exclusion survivorship (compares rates among included pairs only); `is_current` = still in S&P 500, not survived; one-ticker→one-permno map mislabels recycled tickers. "No strong confound" does not follow. | UNVERIFIED |
| R3.12 | credit_proxy_comparison.py:228–238 | Med | Reuses naive pooled z-test FINDINGS #43 already showed invalid (cluster-robust p=0.25 vs naive 0.0056); compares to hardcoded naive VIX figures; no correction for a second proxy. | UNVERIFIED |
| R3.13 | correlation_diagnostic (labeling) | Low | Regime = single-day VIX at window end; "discovered in crisis" overstates what the label means (not lookahead). | UNVERIFIED |

### Batch R4 — regime-strength / PIT-interaction / ML-method scripts
`regime_strength_vs_pit_confirmation.py`, `regime_strength_vs_discovery_regime_test.py`,
`pit_confirmation_vs_regime_interaction.py`, `sequential_bootstrap_ml_comparison.py`,
`quantile_regression_forest.py`, `transfer_entropy_lead_lag.py`, `residual_correlation_factor_test.py`.

| # | Line | Sev | Finding | Status |
|---|---|---|---|---|
| R4.2 | pit_confirmation_vs_regime_interaction.py:76–85 | **High** | Pooled normal two-proportion z-test used at base rate ~0.003% with x_a=16, x_b=0 (expected counts ≪ 5); pairs treated as independent despite shared legs and PIT pairs repeating across 4 cutoffs. Reused by the strength script for "z=3.98, p=0.0001" (PAPER_MAGNITUDE.md §7.7, Finding #66). Needs Fisher/exact test + clustering disclosure. | **CONFIRMED** by code (no small-count guard, pooled normal). |
| R4.4 | quantile_regression_forest.py:145–150 | **High** | Coverage evaluated in-sample only (fit and predict on the same X; script prints "In-sample … coverage check"); saved parquet stores in-sample quantiles as predictions. | **CONFIRMED** by code. Any PAPER.md coverage claim from this script is not out-of-sample. |
| R4.10 | transfer_entropy_lead_lag.py:182; ml.py:360–361 | **High** | TE feature for ml.py computed over the pair's full aligned history (lag also chosen on full history) and attached as a fixed pair-level feature to every EntryEvent → lookahead into train and test. | **CONFIRMED** by code (`pair_row.get("te_directional_diff")`). |
| R4.1 | regime_strength_vs_pit_confirmation.py:52 | High | Strength terciles from full-sample tier-3 EG p-values that include the PIT re-screen's own cutoffs; strongest-span selection gives more-span pairs more chances → "all 16 overlapping pairs are strong" is largely the same statistic twice. | UNVERIFIED (depends on `assign_strength_terciles` span construction — strong lead) |
| R4.3 | residual_correlation_factor_test.py:118, 131–134, 215 | High | One full-history SPY beta per symbol and full-history residual correlation vs the discovery-window 0.40 threshold → does not test crisis-window factor confound (beta rises in crises); full-sample betas are lookahead. §5 "partly a factor artifact" not supported. | UNVERIFIED |
| R4.5 | quantile_regression_forest.py:84 | Med | Pools raw leaf y-values (tree influence ∝ leaf size) instead of Meinshausen's per-point 1/leaf-size weights; docstring claims weighting. | UNVERIFIED |
| R4.6 | sequential_bootstrap_ml_comparison.py:177 | Med | Uniqueness computed against all n labels, not drawn-set-plus-candidate (AFML Snippet 4.5) → "sequential bootstrap" arm ≈ uniqueness-weighted resampling; §7.19 "+3.1pp" compares mislabeled arms. | UNVERIFIED |
| R4.7 | sequential_bootstrap_ml_comparison.py:246 | Low | `random_state=42` hardcoded, no seed arg → PAPER §7.19's "10 seeds, 47.9–72.9%, mean 59.4%" not reproducible from this script. | UNVERIFIED |
| R4.8 | transfer_entropy_lead_lag.py:162, 90–92 | Med | `.dropna()` then positional lag → returns weeks apart paired across DATA_GAPs (GapFlag rule). | UNVERIFIED |
| R4.9 | transfer_entropy_lead_lag.py:144, 206, 214 | Med | p = mean(null ≥ real) without +1 → p=0 possible (PAPER reports "p=0.000" for AMP/RUSHA); min-p over 10 tests per pair unadjusted. | UNVERIFIED |
| R4.11 | regime_strength_vs_discovery_regime_test.py:79 | Low | Inner merge on ordered symbols drops reversed-order pairs from the 56,003-pair chi-square. | UNVERIFIED |

### Batch R5 — portfolio / risk / walk-forward result scripts
`pit_wfa_trade_bootstrap.py`, `pit_wfa_pooled_equity_curve.py`, `stress_test_replication.py`,
`strategy_risk_precision.py`, `portfolio_position_sizing_correction.py`, `portfolio_effective_bets.py`,
`eigenvalue_weighted_position_sizing.py`.

**Shared-module finding (P1), CONFIRMED by code:** `portfolio_math.daily_pnl_from_exits` (line ~33)
is `resample("1D").sum()` over first→last exit — calendar days (weekends = 0) with
`sharpe_from_daily_pnl` annualizing by √252, and no zero-fill outside the exit span. This is the
B11 bias, but in the module documented as the single source of truth for every research metric
(Sortino, rolling Sharpe, Calmar, M2, pooled WFA Sharpe…). Fix once here, not per script.

| # | Line | Sev | Finding | Status |
|---|---|---|---|---|
| R5.1 | pit_wfa_pooled_equity_curve.py:57, 107 | **High** | Each fold's daily P&L spans only first→last exit, not the fold's test window → years of genuine no-trade days dropped (fold1: 11 trades exiting 1946-09→1957-09 of a ~1946–1976 window) → per-fold and pooled Sharpe inflated (~1.6× for fold1). Docstring's "no-trade days stay zero-filled" false at fold edges. | **CONFIRMED** by code (P1 mechanism). **→ FIXED** (commit 85e766fb (P1: daily P&L over the evaluation window, portfolio_math.daily_pnl_from_exits start/end); reconciled 2026-10-03) |
| R5.2 | portfolio_position_sizing_correction.py:129; eigenvalue_weighted_position_sizing.py:176; graphical_lasso_clusters.py:63–64, 73, 113 | **High** | Walk-forward uses cluster labels from `panel.corr()` over layer1 + layer1_holdout combined → test-window correlation informs weights; "not derived from this window's own price history" is false. Inverse-cluster-size arm's OOS edge contaminated. | **CONFIRMED** by code. |
| R5.3 | strategy_risk_precision.py:59–66 | **High** | Groups by symbol pair only, no `hedge_method`/`tf` → OLS+Kalman duplicates double frequency (IQV/Q 80 = 40+40) → implied annual Sharpe ×√2; PNC/ZION (5 per method) passes the n≥10 gate only via duplication. (B4 at the research layer.) | **CONFIRMED** by code. |
| R5.4 | eigenvalue_weighted_position_sizing.py:123, 139, 207 | Med | Zero-loading pair clipped to 1e-8 exposure → ~1e4× weight on a pair that never traded in train; NaN windows dropped per scheme → averages over different window sets. | UNVERIFIED |
| R5.5 | stress_test_replication.py:170 | Med | EG on ~500 baseline days + 12–146 crisis days → p-value is about the baseline; can't detect an in-crisis break; "cointegration holds through stress" doesn't follow. | UNVERIFIED |
| R5.6 | stress_test_replication.py:88–99 | Med | Calm controls added after first run (comment line 88) and not calm: 2018-02-19→04-30 is post-Volmageddon incl. March 2018 selloff; 2015-08 control contains the flash-crash run-up. | UNVERIFIED |
| R5.7 | stress_test_replication.py:297 | Med | Arbitrary 15-point gap, no test, non-independent pair-windows, tiny n → logged as "some support". | UNVERIFIED |
| R5.8 | pit_wfa_trade_bootstrap.py:102, 158, 160 | Med | iid percentile bootstrap on zero-inflated daily series (fold2_roll: 5 nonzero days); all-zero draws silently dropped by nanpercentile; log says "resampling N trades" but resamples days. | UNVERIFIED |
| R5.9 | strategy_risk_precision.py:69, 94 | Med | Symmetric-payoff binomial formula on asymmetric exits (mean vs 3.5σ stop); implied Sharpe never compared to realized; `pnl_net > 0` counts zero as loss; "surviving on frequency" label unsupported. | UNVERIFIED |
| R5.10 | stress_test_replication.py:269 | Low | Log prints `len(sub), len(sub)` → always "N/N pairs tested". | UNVERIFIED |
| R5.11 | eigenvalue_weighted_position_sizing.py:211; portfolio_position_sizing_correction.py:168 | Low | "Established winner" = max over 6–7 schemes of mean non-annualized 21-day Sharpes, no test or multiplicity adjustment. | UNVERIFIED |

Reviewer note: current `trades_layer1` has only 45 OLS trades, so the sizing scripts presently take
their in-sample-only fallback (lines 139 / 183); R5.2/R5.4/R5.11 bite on any run with enough data.

### Batch R6 — statistical-method scripts
`cointegration_regime_segmentation.py`, `crisis_regime_cluster_bootstrap_test.py`,
`eg_null_calibration_montecarlo.py`, `bh_fdr_dependence_check.py`, `bh_vs_by_full_universe.py`,
`threshold_cointegration.py`, `variance_ratio_test.py`, `grid_bootstrap_ar_ci.py`.
(Reviewer line numbers were wrong for eg_null_calibration_montecarlo.py (183 lines) and
grid_bootstrap_ar_ci.py (151 lines); verified locations used below where checked.)

**R4.1 resolved — CONFIRMED circular.** Strength terciles (`cointegration_regime_segmentation.py:181`)
are fit on mean EG p-values of full-history Tier-3 windows (2,520 bars, 252 step) spanning the same
WRDS daily prices, including post-cutoff windows, that `pit_wfa_wrds_daily.py`'s train-window screens
use; `strongest_span_per_pair` takes the best span from any era (no pre-cutoff restriction, unlike
`pit_precision_by_regime_strength.py`). FINDINGS.md ~3850 ("all 16 overlapping pairs are strong,
z=3.98 … strength predicts independent PIT survival") is not independent validation. Combined with
R4.2 (invalid z-test at x=0), this claim should be withdrawn or restated.

| # | Line | Sev | Finding | Status |
|---|---|---|---|---|
| R6.2 | cointegration_regime_segmentation.py:108 | **High** | `or boot_idx == 0` accepts the first raw run regardless of length → 3-window hysteresis skipped at every pair's start; 1-window leading spans with low p labelled "strong". Reviewer on real output: 26,044 / 56,536 coint spans (46%) shorter than 3 windows, all leading, 9,120 labelled strong → skews tercile cutoffs for every downstream test. | **CONFIRMED** by code; counts reviewer-computed. |
| R6.3 | eg_null_calibration_montecarlo.py:67 (docstring :20) | **High** | Single one-direction `coint(a, b)`, no max over both directions, no `longest_gap_respecting_segment`, while the docstring claims "the EXACT production EG-test call" → empirical Type-I rate overstated vs production; §4.2 "elevated null FP rate" doesn't describe the production screen. | **CONFIRMED** by code. |
| R6.5 | grid_bootstrap_ar_ci.py:61, 76 | **High** | Grid capped at ±0.999 and ρ̂±0.15 → confidence set can never contain 1; "every CI sits below 1" true by construction; PNC/ZION@4h [0.9990, 0.9990] is a grid-edge artifact reported as a real bound. Defeats the purpose of Hansen (1999). | **CONFIRMED** by code. |
| R6.4 | eg_null_calibration_montecarlo.py (null construction) | Med | Null pairs = last n bars per series, no calendar alignment (crypto 24/7 vs sessions); samples yfinance cache (~1.5k), not `load_full_universe()`. | UNVERIFIED |
| R6.6 | grid_bootstrap_ar_ci.py:136 | Low | n_grid=40 over 0.30 → ~0.0077 steps; TMHC/WAL CI width 0.0094 ≈ 1–2 steps; PAPER.md's 4-decimal precision is spurious. | UNVERIFIED |
| R6.7 | threshold_cointegration.py (split) | Med | One-sided threshold (z ≤ γ vs > γ), not a symmetric band (|z| ≤ γ) → `outside_faster` doesn't test the transaction-cost-band story (docstring 44–46; PAPER.md ~2208). Null (fixed-regressor wild bootstrap) itself valid. | UNVERIFIED |
| R6.8 | threshold_cointegration.py; grid_bootstrap_ar_ci.py | Med | DATA_GAP rows dropped by mask then treated as consecutive (variance_ratio_test.py already fixed this via `_longest_clean_run`). | UNVERIFIED |
| R6.9 | crisis_regime_cluster_bootstrap_test.py:107 | Med | Calm rate treated as fixed; bootstrap not null-centered, so "fraction ≤ calm" is not a p-value; 12 very unequal clusters (93% in 2) → cluster bootstrap unreliable (Cameron–Gelbach–Miller 2008). "Cluster-robust p=0.25" label overstated (though its direction — non-significance — is the conservative one). | UNVERIFIED |
| R6.10 | bh_fdr_dependence_check.py:20, 111, 116 | Med | Runs BH/BY on `all_candidates.parquet`, which `bh_vs_by_full_universe.py:150–154` says is already BH-confirmed → trivially all confirmed; output uninformative. | UNVERIFIED |
| R6.11 | bh_fdr_dependence_check.py:38 | Low (citation) | Credits BH (1995) with PRDS coverage; that is Benjamini–Yekutieli (2001, Thm 1.2); PRDS never argued for hub-leg-sharing EG p-values. | UNVERIFIED — citation item for step 4 |
| R6.12 | variance_ratio_test.py:199 | Low | q = 0.5–4× half-life on the EG-selected series; large q/n → poorly sized z, VR biased down (Richardson–Stock 1989); no Chow–Denning joint test → "independent confirmation" (PAPER.md ~2216) overstated. Formulas themselves verified correct. | UNVERIFIED |

`bh_vs_by_full_universe.py`: no new issues beyond the one-direction EG already recorded (R1.11).

### Batch R7 — remaining portfolio / risk / method scripts
`dd_hub_effective_bets.py`, `beta_weighted_portfolio.py`, `confidence_score_allocation.py`,
`caviar_dynamic_var.py`, `graphical_lasso_clusters.py`, `financial_turbulence_index.py`,
`decoupling_backtest.py`, `backtest_overfitting_detector.py`, `bertram_ou_thresholds.py`,
`return_smoothing_audit.py`. (Line numbers verified against file lengths this batch.)
Note: CAViaR and return_smoothing read `trades_layer1.parquet` unfiltered (45 OLS + 45 Kalman — B4).

| # | Line | Sev | Finding | Status |
|---|---|---|---|---|
| R7.1 | confidence_score_allocation.py:212–216; asset_volatility_profile.py:52–72 | **High** | Vol profile computed "as of the LAST available bar" of the full cached history, one value per symbol, attached to every trade → ~25% of `confidence_score` is lookahead and constant across trades. | **CONFIRMED** by code. |
| R7.3 | beta_weighted_portfolio.py:194–197 | **High** | Unhedged P&L booked at exit (`daily_pnl_from_trades`) vs hedge overlay marked to market daily → hedge adds variance with no day-by-day offset; hedged Sharpe mechanically lower regardless of hedge value. | **CONFIRMED** by code. |
| R7.2 | confidence_score_allocation.py:78, 131–139 | Med | Percentile scores ranked against the full trade set (incl. future trades); threshold sweep in-sample, no holdout. | UNVERIFIED |
| R7.4 | beta_weighted_portfolio.py:81, 122, 134–136, 178–179 | Med | Exposure live on entry date (earns the pre-entry close-to-close SPY return); 1h entries pad onto that day's daily row (post-entry close) — contradicts "never using data from after entry". Shared by confidence_score_allocation.py:207–208. | UNVERIFIED |
| R7.5 | graphical_lasso_clusters.py:119 | Med | Agreement = `mean(labels == labels_marginal)` on arbitrary fcluster IDs (permutation-variant, different K) → "low agreement" conclusion unsupported; needs adjusted Rand index. | UNVERIFIED |
| R7.6 | caviar_dynamic_var.py:112–114, 125–133, 141 | Med | Exceedance rate measured on the fitting data (≈1−α by the quantile FOC); printed `target=0.95` (should be 0.05); holdout gets its own fresh fit; no DQ test (Engle–Manganelli's adequacy test). No calibration claim supportable. | UNVERIFIED |
| R7.7 | backtest_overfitting_detector.py:86, 92 | Med | `windows[:, -1]/windows[:, 0] − 1` spans window_bars−1 intervals (~20% variance understatement at 5 bars); window_bars=1 → zero std reported as a "real regime mismatch". | UNVERIFIED |
| R7.8 | backtest_overfitting_detector.py:110–114 | Med | Realized/implied vol ratio < 1 expected from variance risk premium; risk-neutral vs physical drift gap expected; no PBO/CSCV (Bailey et al.) anywhere — name overstates. | UNVERIFIED |
| R7.9 | financial_turbulence_index.py:92 | Med | `returns_df.fillna(0.0)` (pre-listing, post-delist, DATA_GAP) → tiny LW variance then Mahalanobis spikes on first real return; violates GapFlag rule. | UNVERIFIED |
| R7.10 | financial_turbulence_index.py:140 | Low-Med | 90th-pct turbulent threshold from full sample; lookahead if used for risk scaling as documented. | UNVERIFIED |
| R7.11 | decoupling_backtest.py:150, 209–211 | Med | Backtest on the same window used for EG selection and hedge fit; 5/142 requalifying < ~7.1 expected by chance; "evidence for the live-pipeline wiring decision" overstated. | UNVERIFIED |
| R7.12 | dd_hub_effective_bets.py:193 (hub generalization 66–81) | Med | Signed ρ̄ averaging with the hub as leg A in some pairs and leg B in others → cancellation inflates Grinold–Kahn breadth; ρ̄ ≤ −1/(n−1) → breadth explodes/negative (n=2, ρ=−0.9 → 20). | UNVERIFIED |
| R7.13 | return_smoothing_audit.py:109, 125 | Med | Exit-date-only irregular series (no zero-fill) → lag-1 ACF links days weeks apart (not GLM's regular MA(2)); at n≈30, SE≈0.18, `xi < 0.8` needs ρ1≈0.17 → flags can be noise; no test. | UNVERIFIED |
| R7.14 | bertram_ou_thresholds.py:106–118 | Low | Cycles not reaching entry within max_bars=5000 still credited full profit; overshoot ignored. | UNVERIFIED |
| R7.15 | bertram_ou_thresholds.py:158–160 | Low | DATA_GAP rows removed and concatenated → OU lag pairs straddle gaps. | UNVERIFIED |

### Batch R8 — final PAPER-cited research scripts
`variance_ratio_test.py` (no new issues), `short_term_factor_alpha.py`, `risk_neutral_density.py`,
`reimers_trio_correction.py`, `price_target_pairs_overlay.py`, `news_impact_asymmetry.py`,
`network_momentum.py`, `multiscale_entropy.py`, `durability_vs_currency_wrds.py`,
`corporate_actions_audit.py`, `audit_price_degeneracy.py`.

**D1 escalated (CONFIRMED by code, data.py:1874–1882):** `_liquidity_filter` compares PER-BAR dollar
volume against `MIN_DOLLAR_VOLUME` ($1M, a daily threshold) at every timeframe. A $20M/day stock
trades ~$50k/minute, so nearly all its 1m bars (and most sub-hourly bars of mid-caps) are NaN'd and
forward-filled with copies of earlier bars that keep their real volume. `audit_price_degeneracy.py`
flags the symptom ("few distinct 1m closes") but attributes it to genuine market data, and cannot
distinguish filter copies (real volume, not necessarily flat OHLC); `corporate_actions_audit.py`
only checks four split dates on 1D. Any intraday result (1m–30m) built on the yfinance cache is
suspect until this is fixed.

| # | Line | Sev | Finding | Status |
|---|---|---|---|---|
| R8.1 | news_impact_asymmetry.py:85 (docstring 15–17) | **High** | "After narrowing" coded as `dz_{t-1} < 0`; narrowing is `sign(dz) == −sign(z)`. With z on both sides of 0, each group is ~half narrowing/half widening → variance ratio pulled to 1 by construction. PAPER.md §7 "clean null across 22 pairs … `garch_stop`'s symmetric design is validated" is what the bug produces. | **CONFIRMED** by code. Claim must be withdrawn pending re-run. |
| R8.3 | network_momentum.py:62–65, 156 | **High (claim)** | W = full-sample corr(r_i[t], r_j[t+1]), positive edges kept, scored on the same r_j[t+1] → signal correlated with target by construction; `_CALIBRATION_WINDOW` unused except abort check. | **CONFIRMED** by code; the docstring discloses "full available history … signal-existence test", so the issue is PAPER.md's "genuine +0.046 incremental edge" wording — step-4 honesty item. |
| R8.4 | multiscale_entropy.py:96 | **High** | r = 0.2·std recomputed per coarse-grained series; Costa et al. (2002) fix r from the ORIGINAL series. Re-normalizing cancels the variance-shrinkage MSE measures (white noise comes out flat instead of falling). Interpretation and synthetic-reference claims depend on it. | **CONFIRMED** by code (r computed from the function's input `x`). |
| R8.9 | price_target_pairs_overlay.py:81 | **High** | 100% of entry_times are intraday (09:30); daily series at midnight + `pad` → returns the entry day's 16:00 close (up to 6.5h future), mechanically linking post-entry moves to agree/disagree labels. | UNVERIFIED (reviewer checked real trades file) |
| R8.2 | news_impact_asymmetry.py:157, 83–84 | Med | NaN deltas removed and packed → `dz[1:]/dz[:-1]` pairs across DATA_GAPs (lag-bridging moved, not removed). | UNVERIFIED |
| R8.5 | multiscale_entropy.py:145–146 | Med | DATA_GAP rows masked out before coarse-graining → blocks/templates span multi-day outages. | UNVERIFIED |
| R8.6 | short_term_factor_alpha.py:100, 130 | Med | Monday dummy shifted one row → tests Tuesday; French (1980) "negligible (corr=0.004)" is a Tuesday test. | UNVERIFIED |
| R8.7 | short_term_factor_alpha.py:55 | Low | Full-sample per-column z-scoring → mild lookahead in pooled correlations. | UNVERIFIED |
| R8.8 | reimers_trio_correction.py:52, docstring 11 | Med (citation) | Reimers factor (T − n·k)/T uses k = `k_ar_diff` (= k−1) → correction halved; at T in the thousands the factor ≈ 0.997 either way, so "0 flips" is guaranteed by T, not evidence. | UNVERIFIED |
| R8.10 | price_target_pairs_overlay.py:81 via options.load_price_series | Med | `close_total_return` compounds dividends above quoted price; IBES targets are price terms → divergence partly measures dividend-yield difference. | UNVERIFIED |
| R8.12 | durability_vs_currency_wrds.py:46–50, 72 | Med | Full-sample EG (n=13,373) vs last-5y EG (n≈1,260) → lower power read as "already failed"; `output/research` not created. | UNVERIFIED |
| R8.13 | risk_neutral_density.py:212 | Low | `implied_vol_from_price` default r=0, no dividend yield → density integrates to ~e^{−rT}; carry absorbed into IV. | UNVERIFIED |

---

## STEP 1 COMPLETE — summary (2026-09-26)

Reviewed: all 11 core modules (6 groups) + all 60 PAPER.md/PAPER_MAGNITUDE.md-cited research scripts
(8 batches). ~190 findings logged; 4 FIXED (group 1); ~60 CONFIRMED by code read and/or real-data
measurement; remainder UNVERIFIED leads, each with a concrete check.

**Systemic, result-invalidating (CONFIRMED), in dependency order:**
1. Data layer — D1 (liquidity filter fabricates bars at every TF; forex 100% NaN), D2 (daily cache frozen
   since 2026-06-17), D3/D4 (1h/4h snapping lookahead + lost bars), D16 (1,647 truncated WRDS files on
   CachyOS, silently dropped), U4/R1.1 (price-only WRDS close; Compustat Global in local currency, no FX
   — 498/929 confirmed pairs), M7 (CPI/FEDFUNDS released ~4 weeks early).
2. Discovery — A1 (EG never runs on pairs with different history start in analysis.py main path; also
   excluded from BH m), S3 (Purity pair-level selection lookahead; "Genuinely PIT-safe" overclaim),
   R1.6 (81% single-window confirmations; pair-level FDR ≤ 9.1%, not 5%).
3. Backtest/P&L — B2 (β-drift is all of the sampled positive P&L), B3 (log units vs dollar cost), B4
   (OLS/Kalman double count), P1 (portfolio_math calendar-day √252 + exit-span-only zero fill).
4. Inference — S5 (reality-check bootstrap not demeaned: reported p=0.559/0.546 uninformative), R2.1
   (DSR trial registry double-merged: 1,150 vs 570 unique), R2.3 (no purging/embargo in ml.py or LSTM:
   09-22 AUCs not clean OOS), R4.10 (TE feature lookahead into ml.py).

**PAPER.md claims that cannot stand as written (step-4 inputs):** Purity "Genuinely PIT-safe" (§7.20);
White Reality Check p-values (line 458); strength-vs-PIT "independent survival" z=3.98 (R4.1/R4.2/R6);
crisis persistence gap (R3.1) and sector test (R3.7 outcome-driven asymmetric censoring); news-impact
"symmetric design validated" (R8.1); network-momentum "genuine incremental edge" (R8.3); grid-bootstrap
"every CI below 1" (R6.5); EG null "elevated FP rate" (R6.3); every Sharpe/DSR/capital-sim number (B2–B4, P1).


---

## Post-review updates (2026-09-26/27)

**D1 FIXED (code).** `DataCleaner._liquidity_filter` and its call removed from `data.py`; `clean()` no longer
rewrites observed prices. `debug/_verify_liquidity_filter_no_fabrication.py`: 4/4 with the fix, 0/4 on the pre-fix
code (intraday closes kept 0% -> 100%; low-volume daily bars exact; zero-volume daily 0% -> 100% non-NaN). First run
had a fixture flaw (bdate_range includes NYSE holidays that `clean()` correctly drops) — fixed in the test, not the
module. Data-layer verify suite: 6/6 pass; `_verify_data_wrds.py` timed out at 600s (documented live-WRDS slow
script, HANDOFF:557; doesn't touch this path). **The on-disk yfinance cache still contains the fabricated bars
until re-fetched** (blocked on D2 — the refresh never runs). The Purity pipeline reads raw `output/cache/wrds/` via
`universe_loader`, which never passed through `clean()`, so it was not exposed to D1.

**R2.3 measured (step 3, `research/ml_model_comparison_purged.py`).** Purging + a 1% (~214-day) embargo, with the
TE features excluded (R4.10), changes XGBoost's test AUC from 0.6062 (positional) to 0.6067 (purged). The label-
overlap leakage R2.3 describes is real in the code but did not materially inflate the AUC; the 09-22 AUC (0.6075)
survives both purging and removal of the lookahead TE features. R2.3 stays open as a code fix (ml.py itself still
splits positionally), but its measured effect on the headline AUC is ~0.

**B16 NEW, CONFIRMED on real data.** Entry has no upper |z| bound while STOP_ZSCORE = 3.5, so a trade can open
already past its own stop. Momentum-gate 1D OLS trades (24,047): **65.5% exit after <= 1 bar, 99.9% of those via
`stop`, 96.8% of those entered with |entry_z| >= 3.5** (vs 12.7% among longer trades). Two-thirds of all trades are
immediate stop-outs; every trade-level statistic (win rate, hold time, P&L distribution) is dominated by them. The
underlying fact was noted 2026-07-12 (portfolio_sim.py comment, "45% of real trades enter with |entry_z| >=
STOP_ZSCORE") but its consequence was not. `--entry-z-max` exists; to be evaluated as a comparison arm in the P&L
rebuild, not changed silently.

**B2/B3 comparison arm built and run (2026-09-27).** `pnl_dollar.py` (verify 12/12, incl. hand-computed cases and a
penny-stock fixed-notional case) marks both legs at real prices with the hedge fixed at entry:
gross = side · N_a · (r_a − β_entry · r_b), total-return legs, dollar costs; GVKEY (local-currency) legs → status
`non_usd_leg` (not a number) until the USD conversion is built. Three real trades recomputed by hand from the raw
WRDS files match the module to the cent; one of them (KMB/PERMNO79057) made +$52.98 while the old P&L booked −3.71.
Default sizing is fixed dollar notional per trade, because fixed 100 shares at split-adjusted prices makes early trades
negligible (AMAT 1991 adjusted $0.42 → a $42 position) — found in that hand check.

Real result, OLS trades, USD-only pairs (~31% of trades), business-day Sharpe:

| Gate / split | old pnl_net | dollar net | dollar gross | immediate-stop share (B16) | gross excl. B16 |
|---|---|---|---|---|---|
| momentum IS | +0.132 | **−0.408** | −0.191 | 65% | −0.119 |
| squeeze IS | +0.474 | **−0.386** | −0.227 | 60% | −0.191 |
| combined IS | +0.721 | **−0.354** | −0.248 | 53% | −0.219 |
| momentum OOS | −0.184 | **−0.296** | −0.125 | 66% | −0.157 |
| squeeze OOS | +0.667 | **−0.078** | +0.003 | 61% | +0.031 |
| combined OOS | +0.601 | **−0.005** | +0.048 | 51% | +0.079 |

Every positive gate Sharpe was produced by the accounting (B2/B3). In-sample every gate loses money before costs;
out-of-sample momentum loses and squeeze/combined are ≈ 0. Not yet covered: GVKEY pairs (69% of trades, pending
USD conversion), the capital-constrained replay on dollar P&L, and the data-layer fixes still open.

**Rule-invariant audit (2026-09-27, `research/strategy_rule_invariants.py`, verify 11/11).** Every backtest.py
rule checked against all 101,700 trades in the six current gate files (Config: ENTRY 3.0, STOP 3.5, EXIT 0.0,
MAX_HOLD_MULTIPLIER 2.0, MIN_HALF_LIFE_BARS 5).
- **Mechanically correct, 0 violations:** entry threshold, side vs z sign, stop level reached on every stop, signal
  exits crossed, max-hold at its limit, no overlapping positions per pair, half-life floor, and every squeeze /
  momentum gate decision re-checked at the actual entry bar from the spread files (47,628 entries, 0 violations).
- **B16 quantified — enter/stop/re-enter churn loop (design defects, code does what it says):**
  I2 entries at or past the stop 54–68% of trades; S1 stopped after a FAVORABLE move 32–40% (stop is `abs(z) >=
  STOP`, not direction-aware, so any entry at/over the stop is stopped next bar whichever way z moves); S3 re-entry
  within 1 bar of a stop 19–38%; S2 overshoot-through-zero recorded as a stop: 0–7 trades (rare).
- **Dead default rules:** `corr_exit` never fired in 101,700 trades — structurally impossible (needs |z| > 2|entry_z|
  ≥ 6, checked after the |z| ≥ 3.5 stop; its comment says 2.5×, code 2.0×). `data_gap` never fired (B1).
- **Stale documentation:** backtest.py module docstring and `--entry-z` help both state ENTRY_ZSCORE = 2.0; actual 3.0.
Fix candidates (comparison arms, not silent changes): ENTRY_ZSCORE_MAX < STOP_ZSCORE; direction-aware stop
(stop only on adverse |z| widening beyond entry); re-entry cooldown after a stop.


**Small data-layer / stats fixes (2026-09-27), each with a failing-then-passing test unless noted:**
D14 FIXED — size guard moved INTO `_save_sp500_cache` (single `_SP500_MIN_VALID = 400` constant replacing three
literals); `_verify_sp500_cache_guard.py` 1/3 → 3/3. C13 FIXED — `clean()` derives a missing `MIN_BARS_REQUIRED`
entry from `MIN_OVERLAP_BY_TF` (3M/6M/1Y: 8/4/10) instead of a flat 100; `_verify_min_bars_long_tfs.py` 3/6 → 6/6.
S7 FIXED — Zivot–Andrews break index read from tuple index 4; `_verify_za_breakdate_index.py` 1/2 → 2/2 (statsmodels
ordering confirmed on a planted break). D15 FIXED by code reading only (`_attempts[0][0]` → `_attempts[0]`; inside a
live yfinance fetch — no unit test, disclosed). D16 FIXED (restore, see Development.md). Stats/data verify suite: 11/11.
D3/D4 FIXED (2026-09-27) — `snap_timestamps` now CEILS each bar onto the session grid (a label can never be
earlier than the bar's real start → no lookahead by construction), keeps the final partial session slot (1h
09:30..15:30; 4h 09:30 and 13:30), and MERGES colliding bars (first open / max high / min low / last close /
summed volume) instead of keeping one. `_verify_snap_timestamps_no_lookahead.py` 0/7 → 7/7 (first draft's collision
case encoded the old rounding and was corrected). All 4 snap_timestamps verify scripts pass. A bar starting after
the last slot opens is dropped (only occurs for finer-than-TF input). Intraday caches on disk were written with the
old snapping → regenerate with the data re-fetch.
D2 FIXED (2026-09-27) — three stacked defects in the daily incremental refresh: (a) the exists-only cache check
returned the OLD file without downloading (demonstrated: legacy call made 0 daily download calls and returned the
2026-06-17 cache), (b) a real 1-month slice would fail the 100-bar minimum, (c) get_equity_history then
`DataStore.save()`d its result, which would have REPLACED each full history (and its 7D/1M) with the slice.
`get_equity_history(..., incremental=True)`: forces the download, accepts the slice (`clean(min_bars_override=1)`),
returns 1D only and never saves; the caller merges via `DataStore.append` and re-derives 7D/1M from the merged
history. `_verify_daily_incremental_refresh.py` 4/4 (338 → 347 rows, last bar 06-17 → 06-30, cache untouched by the
fetch); data-layer verify suite 13/13. The yfinance cache re-fetch itself is still to run.
A1 FIXED (2026-09-27) — `analysis.align_to_common_index()` reindexes every aligned frame onto the union timestamp
index (no forward-fill) right after `DataAligner.align_universe` in `analysis._run_one_tf` and `pit_wfa`'s screen
(S1). `_verify_eg_common_index_a1.py` 6/6 (cointegrated synthetic pair with different listing dates: EG runs, p≈0,
n_overlap exact); real AAPL/MSFT/ABNB now tested (ok=True, overlaps 10,144 / 1,385). BH denominator:
`_combine_eg_directions` keeps CRASHED tests in m with p=1 and counts/logs insufficient-overlap pairs
(`_verify_eg_bh_denominator.py` 5/5). Regression suite over every verify script touching EG/alignment/pit_wfa: 35/36,
the 1 failure a stale calendar-day expectation from the P1 fix (Fri+weekend → 1 business day), corrected.
Research-script `align_universe` call sites (~20) NOT changed — each to be reviewed case by case.
yfinance DAILY cache regenerated (D1+D2): 1,641/1,645 symbols (4 restored: CWEN-A, HLX, LEG, UNI — no Yahoo data);
equity median flat days 10.8% → 2.9%; files >20% flat 544 → 46; forex 100% NaN → real series; history to
2026-09-27. Originals in `output/cache/_yf_daily_backup_20260927/`. Intraday caches NOT touched (irreplaceable
history; decision for Ross).
Churn-loop arms built (`--storm-directional-stop`, `--storm-reentry-rearm`, default off; `--entry-z-max` existing):
`_verify_churn_fix_arms.py` 5/5 (fixture first drafted too steep to show repeated churn — corrected).

**Churn-loop and dead-code-pathway comparison arms (2026-09-27; `research/churn_arms_eval.py`).** Momentum gate,
Purity pool, OLS, dollar P&L on USD-only legs, business-day Sharpe; 7 arms × IS/OOS = 14 trials.
| Arm | IS net / gross | OOS net / gross | mechanism check |
|---|---|---|---|
| base | −0.408 / −0.191 | −0.296 / −0.125 | 68% entries past stop, 39% favourable stops, 35% re-entry churn |
| entry cap 3.5 | −0.278 / −0.196 | −0.278 / −0.215 | entries past stop → 0% |
| directional stop | −0.278 / −0.150 | +0.039 / +0.133 | favourable stops → 0% |
| re-entry re-arm | −0.140 / −0.065 | −0.082 / −0.021 | re-entry churn → 0% |
| all three | −0.168 / −0.100 | −0.159 / −0.103 | all three patterns → 0% |
| real_corr_exit (flag rule) | −0.737 / −0.157 | −0.207 / +0.249 | fires 8,779 / 2,089 times |
| decoupling_avoidance_exit | −0.405 / −0.188 | −0.296 / −0.125 | fires 14 / 0 times — effectively a no-op |
Each fix removes exactly the defect it targets and cuts losses by up to two-thirds, but no arm is profitable in-sample
even before costs; the one positive number (directional stop OOS +0.039) is 1 of 14 trials and not evidence.
`corr_exit` (default rule) remains structurally unreachable — its intent is covered by `real_corr_exit`; `data_gap`
force-close becomes testable only once gap flags survive into spread files (B1/D-series).

**Data-layer round 2 (2026-09-27):** U4 FIXED (loader uses CRSP close_total_return, float64; test 2/6 → 6/6).
D5 FIXED — `align_intraday` masks closed-market rows (non-crypto: missing rows at a time of day the asset never
trades → DATA_GAP), so a 4h weeknight is no longer FILL (test: 56 overnight FILL rows → 62 DATA_GAP; crypto
unaffected; 24-script gap/alignment suite passes). U2 FIXED — `align_to_common_calendar` converts tz-aware
intraday stamps to ET before dropping the tz (Binance 14:30 UTC → 10:30 ET), daily keeps its date (test 1/4 →
4/4 incl. existing calendar/loader suites). **D11 NOT changed, by design for now:** `data._standardize` strips tz
without converting, but `snap_timestamps`' BUG-D57 fix relies on that (a naive index for an exchange-suffixed
symbol is treated as that exchange's local time); converting there would silently break .L/.T/.HK intraday.
Needs a coordinated redesign of both functions; current pool exposure nil (intraday pairs are US equities, ET).
FX: `fx_convert.py` (8/8 hand-computed) built; per-listing currency periods + Compustat daily rates (205
currencies, incl. legacy) being fetched; ADR real-data check pending.

**Data-layer round 3 (2026-09-27).** Every fix: failing test first, then the fix, then the related suites.
- **D13 FIXED** — 1M/3M/6M (data.py) and 3M/6M/1Y (data_wrds.py) bars were stamped at period START carrying the
  period-END close (real case: a 6M bar dated 2023-01-01 held the 2023-06-30 close; old 2QS bins were even anchored
  Apr/Oct on a March-start series). New `period_bars.py`: every coarse bar stamped at the CALENDAR period end
  (Friday, month/quarter end, Jun-30/Dec-31, Dec-31), shared by data.py, data_wrds.py and both IBKR derivations;
  WRDS native CRSP monthly (last trading day) restamped to month end so equity and 24/7 crypto share stamps. Test
  25/25 (`_verify_period_end_stamps.py`); WRDS verify (live) passes. Caches migrated
  (`research/restamp_coarse_bars_d13.py`): 21,136 files (yf 7D/1M/3M/6M ×1,718 + 12 new; WRDS 7D/3M/6M/1Y ×2,843,
  native 1M ×2,844), originals in `output/cache/_backup_d13_20260927/`; all 21,136 re-checked period-end stamped.
- **D7 FIXED** — `align_intraday`'s OOM guard returned the raw index with every flag NONE (off-grid, overnight jumps
  unmasked). Now keeps the grid and drops only the oldest history beyond `_MAX_REINDEX` rows (warning logged).
  Test 2/4 → 4/4.
- **D9 FIXED (worse than logged)** — `_roll_adjust` treated any >5% futures/commodity move as a roll AND its ratio was
  inverted, so each such move was roughly DOUBLED (synthetic +12% → +25.7%). Raw yfinance =F history: 41 ES days
  (2008-10-13 +14%, March 2020), 311 CL, 894 NG, 22 GC, 204 KC; ZN 0 (real equity-index/bond roll gaps are <1%, so
  the rule never caught an actual roll). Removed; cleaning no longer rewrites futures prices. **Disclosed bias:**
  yfinance =F series are unadjusted front-month, genuine roll gaps remain. **Open methodology item for Ross:** roll
  handling from real contract calendars. The 27 cached futures/commodity daily files were written with the doubling
  and need a refetch. Test 0/3 → 3/3.
- **D10 FIXED** — `IBKRFeed.get_bars` (useRTH=False) cached cleaned-but-unsnapped bars (extended hours, off-grid);
  only 1 of 5 callers snapped afterwards; its yfinance fallbacks were cached unsnapped too. Now snaps before every
  cache write (snap verified idempotent at 1h/15m/4h/1D). Test 1/3 → 3/3 (2,560 cached bars incl. 04:00-19:00 → 960
  session bars).
- **D12 FIXED** — append-seam reconciliation compared existing's LAST close with new_df's FIRST close (different dates;
  an overlapping 1mo refresh mixed a month of returns into the "ratio"), and yfinance auto_adjust's dividend basis
  shifts (under the 15% tolerance) were never reconciled. Now measured on overlapping timestamps (median new/old,
  applied only when ≥80% of overlap rows agree within 0.1%; separate volume ratio); the recorded-split check kept
  for the no-overlap case. Test 3/6 → 6/6; BUG-D65 and IBKR-merge split suites still pass.
- **M8 + M9 FIXED** — COT was visible on its Tuesday as-of date (released Friday); daily FRED series had no lag
  (RegimeConditioner's `index <= entry date` saw same-day VIX close, 16:15 ET); DTWEXBGS (H.10, released Monday for
  the prior week) visible up to a week early. `macro._release_available`: visible the first trading day strictly
  after release (daily: next day; DTWEXBGS: Tuesday after the following Monday; COT: Monday after Friday). Old code
  confirmed same-day on the same inputs. Test `_verify_macro_daily_cot_availability.py` 4/4; M7 test still 4/4.
  Latent (Layer 2 off). Holiday-week COT releases can still be 1-2 days later than modelled (disclosed).
- **C14/C15** comments corrected (production entry z = 3.0; binary regime sizing is 1.5×/1.0×). **C16** `_IO_WORKERS`
  derived from `os.cpu_count()` (capped at the benchmarked 32).
- **A1 follow-up, research call sites.** (1) `UniverseFilter.build_returns_matrix` LEFT-padded per-symbol returns (assumes
  a common END bar): a symbol ending earlier (delisted, stale) was shifted against all others — identical-return legs
  measured corr 0.0011. Now aligned on real timestamps (union index, no fill); identical output for common-index input
  (production path). Test 1/3 → 3/3. (2) `CointScanner.scan`/`rolling_fraction` now reindex their candidate symbols to
  one shared index themselves (fast path: no copy when already shared). Direct callers `research/pit_wfa_wrds_daily.py`
  and `research/threshold_relevance_pit_test.py` skipped that step — on the old code a cointegrated pair with
  different listing dates was tested but never confirmed; now confirmed (test 1/3 → 4/4). **Results previously
  produced by those two scripts under-tested such pairs and must be re-run before being cited.** Pair-level callers
  (episodic_pairs_adapter — the Purity source —, pit_wfa_episodic, decoupling_backtest, aligned_pair_loader,
  confirmatory_cointegration_check, ridge) already intersect indices: unaffected. Correlation-matrix callers
  (cross_tf_lead_lag_scan, cross_timeframe_cointegration, k_bahc, inverse_polarity, structural_break_onset,
  near_miss_lag_scan, bh_vs_by_full_universe) are fixed by (1).
- **D16 NEW → FIXED 2026-09-27 (Ross: "fix the mixing") — cross-asset-class symbol collisions.** Found while preparing the D9 futures
  refetch. (a) `DataStore` keys cache files by symbol only, and 4 universe symbols exist in two classes: CL
  (Colgate / crude), ES (Eversource / E-mini), CC (Chemours / cocoa), LTC (LTC Properties / Litecoin); whichever
  wrote last owns the file — today `ES_1day`/`CL_1day`/`CC_1day` are the stocks (ES last close 63.67, not ~6,500).
  (b) `universe_loader` merges WRDS last, so Binance Litecoin (`binance/LTC_1d`, 44.16) is shadowed by LTC
  Properties. (c) `_to_yf_ticker` has no futures/commodity branch (the intraday path appends `=F`), so a daily
  futures fetch downloads the same-named stock. 12 of 27 futures/commodity symbols have no daily file at all; the
  rest are short (2020+ or 2025+). Pool exposure checked: k1 has 2 ES pairs (APA/ES, ES/PERMNO75341) built from
  WRDS — Eversource, the intended instrument; k2 none.
  **Fix:** `instrument_labels.py` — crypto labelled `<SYM>-USD`, futures/commodities `<SYM>=F` (Yahoo's own tickers;
  equities/ETFs/intl/forex unchanged). Applied where labels are born (`UniverseBuilder._build_raw_list`), in
  `_to_yf_ticker` (now the single mapping; the intraday fallback's drifting copy removed), in `_build_contract`
  (IBKR uses the root), and to Binance labels in `universe_loader` (loader version bumped). Side effect fixed:
  `_is_crypto` (suffix-based) now recognises every crypto label — bare labels got equity gap handling wherever the
  class map was not passed. Test `_verify_instrument_labels_no_collision.py` 2/9 → 9/9. Cache migration
  (`research/migrate_instrument_labels_d16.py`, dry-run first; the ownership rule was corrected twice on the dry-run
  table — full-history level test broke on decades of dividend adjustment, Pearson corr on glitch days; final rule:
  recent-250-day return agreement, level gap as a loose bound, coarse files follow their 1day file): all 52 files
  under CL/ES/CC/LTC are the stocks and stay; 225 crypto/futures/commodity files moved to namespaced names
  (backups in `output/cache/_backup_d16_20260927/`). Note: 27 crypto/futures roots also exist as (mostly historical)
  WRDS stock tickers (BTC, SOL, GC, NG, ZN, ...); in the loader these now stay separate labels.
  **D9 refetch done:** `refetch_yfinance_daily_cache.py --classes futures,commodity --include-missing` — 25/27
  regenerated with ~26 years each (12 had no file, the rest 2020+/2025+); ES=F last 7,773.5 with 2008-10-13 +14.1%
  and 2020-03-16 −10.4% intact (not doubled). DX=F does not exist on Yahoo; PL=F is rejected by the new D8 gate
  (12.9% missing over its life: a 2002-2009 Yahoo hole, ~3.4% since 2010) — see D8.
- **D8 FIXED** — `_fill_gaps` reindexed IBKR "1 day" bars onto NYSE sessions and forward-filled before the cache write
  (fabricated bars of any length stored as real; crypto weekends dropped), and yfinance/WRDS callers pass "1D", which
  matched no branch, so `MAX_MISSING_PCT` never applied to them. Replaced by `_measure_missing`: never adds rows;
  missing share against the asset's own calendar (all days crypto, weekdays otherwise); history before the last
  252-bar (MIN_OVERLAP_BY_TF["1D"]) window above the threshold is dropped, not the asset; a currently-unreliable
  asset is rejected. The rule was chosen on real data: lifetime missing share >10% for 0/1,730 yfinance files but
  11,103/40,462 WRDS files (illiquid names, foreign holidays) and it rejected PL=F whole (2002-2009 Yahoo hole, 3.4%
  since 2010); my first trim cut after the last bad window's END (dropped ~10 clean months) — corrected to one bar after
  its START, which is exactly "every window of the kept span meets the threshold". Test 1/4 → 5/5. Effect on the WRDS
  files data.py cleans (production function): 3/1,490 equities rejected, 402 trimmed (median 17% of rows, median 35
  years kept), ETFs 0 rejected / 1 trimmed. `DataCleaner` is not on the research-loader/pool path.
- **D17 NEW → FIXED 2026-09-27 — WRDS files under a current ticker holding a different security.** The 3 D8 rejections exposed it:
  WRDS `TPC` is a 1992-2000 company (today's TPC = Tutor Perini), `VSNT` 1996-2012 (today = Versant, 2025 spin),
  `WSO` 86-94% missing recently (likely the Class B line). Across all 1,573 labels in both yfinance and WRDS, 43
  (2.7%) disagree (no overlap, or <80% daily-return agreement on the last 250 common days) — e.g. SNDK (old SanDisk,
  to 2016), BBBY, P (Pandora), BLD (1929-1968), KW (1925-1973). WRDS wins label collisions (loader) and is primary in
  data.py, so these replace the current company.
  **Root cause:** `research/full_us_market_price_fetch.build_full_market_label_map` gave a reused ticker to the FIRST
  permno `build_delisted_label_map` saw, and permnos arrived oldest-first: 2,719 of 4,327 reused tickers went to an
  older holder, 707 of them displacing a company listed today (label `A` → a pre-1999 company, not Agilent; `AAP`,
  ...). S&P names mostly survived only because data_wrds.py's S&P path (active-permno resolution) had written those
  files first and the full-market fetch skipped existing labels. Second cause: the legacy `stocknames` master is
  frozen at 2024-12-31, so 2025 listings (SanDisk's 2025 spin = SNDK today, Beyond = BBBY, Qnity = Q) were unknown.
  **Fix:** most recent holder claims the ticker (currently listed first, then latest name-end, then the share class
  whose trading symbol is the ticker); security master rebuilt from CIZ v2 `stksecurityinfohist` (30,256 permnos,
  current to 2025-12-31, superset of legacy 29,366). Test `_verify_full_market_label_recency.py` 1/3 → 3/3.
  **Cache relabel** (`research/relabel_wrds_by_recency_d17.py`, dry-run first; file identity from CONTENT because files
  don't carry a permno and two scripts write the same names): a file is identified when its first..last date lies
  inside exactly one candidate permno's listing span (tie-break: the span of that permno's spell under THIS ticker).
  Three dry runs corrected the rule — span IoU left 6,651 files (incl. AAPL) unidentified because fetches start after
  listing; current securities' open spells have NaT end dates that max() skipped (AAPL's span "ended" 2007);
  a current company's permno span can contain a dead company's period (TPC). Applied in two passes (legacy master:
  4,603 labels moved; v2 master: 448 more), 1,184 duplicate files and 14 stale files (unidentifiable, under a
  currently-listed owner's ticker but ending >1 year before data end, e.g. TPC 1992-2000) set aside in
  `output/cache/wrds/_backup_d17_20260927/`; nothing deleted; pre-fix label map kept as
  `full_us_market_label_map_pre_d17.parquet`. 1,859 mapped labels had no file — all fetched (0 empty) through the
  persistent WRDS session (`research/wrds_session_server.py`); coarse files derived for 31 universe labels (124 files)
  and their native CRSP monthly fetched. yfinance↔WRDS identity mismatches: 43 → 19.
  Watsco: permno 46068 (86% "missing") is the Class B line trading ~17 days/yr — genuine; WSO now → 66376 (Class A).
  **Post-data-end listings** (VSNT = Versant 2026 spin; CRSP ends 2025-12-31): the dead company legitimately keeps the
  WRDS label, but the loader must not let it shadow the current yfinance series. **Loader rule (fixed):** when a WRDS
  series ends before the same-label yfinance series begins, or more than a year before it ends (a delisted security
  cannot still be trading; CRSP's own data end is < 1 year old), yfinance keeps the ticker and the WRDS series stays
  in the universe under its PERMNO<n> label (`_verify_loader_disjoint_sources.py` 4/4). **Residual, open:** 6 labels
  where both sources are current but daily returns disagree (FOSL, INCR, CALY, NKTR, SCOR, SPWR — 2024-25 ticker
  transitions / corporate actions); case-by-case.
- **D19 NEW — 3,256 WRDS 1D files with no valid price.** All 3,256 permnos have rows in `dsf_v2`; spot checks
  (FRME, AMSC) show clean trade prices, while the cached files hold ~450-800 all-NaN rows — remnants of an earlier
  broken fetch. Being refetched (backups `output/cache/wrds/_backup_empty_refetch_20260927/`). 2,758 of the permnos
  have `dlyprc` but no `dlyclose` over their whole history. **Refetch result:** 498 recovered with valid prices (median
  996 rows); the 2,758 still without a close are ALL Nasdaq securities that ended by 1992 (median 1985, first 1972) —
  pre-1992 Nasdaq reported bid/ask quotes only, so CRSP holds a quote midpoint and no trade close. **Kept excluded
  and disclosed:** early Nasdaq small caps (1972-1992) are absent from the deep-history universe (a coverage bias for
  pre-1993 windows). Using |dlyprc| is the standard CRSP convention but would put quote-midpoint-only series into the
  universe — decide together with D18.
- **D18 NEW, OPEN (for the sweep) — trade prices vs quote midpoints.** CRSP `dlyclose` is null on no-trade days, but
  `dlyret` (→ `close_total_return`) uses the bid/ask midpoint there. The loader prefers `close_total_return`, so for
  illiquid names it mixes midpoint moves into a series other paths treat as trades (Watsco B: 17 trades/yr, a TR value
  every day).
- **R1.1 FX conversion APPLIED (Surface, 2026-09-28 00:03).** `research/apply_fx_to_wrds_global.py` over the 15,195
  Compustat Global labels: 15,093 converted (`close_usd` added), 101 had no file, 1 had no currency periods; median
  USD coverage of rows 100%, 14 files < 90% covered. Null-currency periods (22,370 across 12,856 gvkeys, many one-day
  1984 stubs) convert to NaN, never to an unconverted local price. Report
  `output/research/apply_fx_to_wrds_global_report.parquet`. ADR real-data check still pending.
  **ADR real-data check (2026-09-28):** USD-converted Compustat listing vs its US ADR (CRSP), last 250 common days,
  median ADR/USD-price ratio vs the ADR share ratio: HSBC London 5.03 and HK line 5.05 (5), BP 6.00 (6), Shell 2.01
  (2), AstraZeneca London 0.50 / Stockholm 0.50 (0.5), Honda 3.00 (3), Toyota 10.0 (10), Sony 0.97 (1) — all with
  tight IQRs, so no pence/pounds or minor-unit scaling error and the SEK/JPY/HKD conversions are right. Daily-return
  correlation 0.4-0.8 (asynchronous closes across time zones, expected). **Residual, open:** Unilever 1.089 vs 1.0 — a
  persistent ~9% gap to explain (share line or ADR ratio).

**2026-09-28 updates.** A6/S10 CONFIRMED + FIXED (crashed / never-computed rolling-coint tests passed the coint_frac
filter; details in docs/INCONSISTENCY_SWEEP_2026-09-27.md "2026-09-28 additions"). ML gate fails closed. Compustat
`trfd` total return verified and implemented (apply pending the fetch). Loader/pnl_dollar silent drops surfaced.
Lineage guards now cover the intraday scan; the 1D scan's `--fresh` only moves its own checkpoints.

**Ledger reconciliation (2026-10-03).** The table's status column lagged the prose updates. Each mismatch was checked
against an explicit status statement (a keyword heuristic produced false positives, e.g. R6.3 / R6.5 / R8.3 / R4.1
sat near another finding's "FIXED" — left unchanged). Marked FIXED with evidence: A1, D1, D2, D3, D4, D5, D14, D15,
S7, U2, U4, C13. **Needs a manual decision:** B1, B2, B4 (the P&L findings) — addressed by the dollar-P&L work
(`pnl_dollar.py`, `pnl_mode="dollar"`) but no explicit FIXED statement, and legacy P&L still exists as a mode.
**ID collision fixed:** the COT name-prefix truncation was first published as "M12", already the ID of this table's
"daily series ffilled with no staleness flag" finding; renamed **M13** in code comments, tests and docs (commit
messages from 2026-09-27/28 still say M12). Status counts after reconciliation (175 rows): FIXED 25, CONFIRMED and
open 40, UNVERIFIED 108, other 2.
