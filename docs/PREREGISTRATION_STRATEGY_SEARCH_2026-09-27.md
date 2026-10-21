# Pre-registration — strategy parameter search (Design 1), 2026-09-27

Committed BEFORE any search result exists. Anything in the eventual write-up that departs from this document
must be labelled as a deviation, with the reason. Ross approved the design 2026-09-27 ("i like designs 1 and 2";
holdout splits 50/50, 60/40, 70/30, 80/20 — all four reported, none chosen after the fact).

## Question
Does ANY configuration of the mean-reversion strategy, on a point-in-time-safe pair pool and under corrected
dollar accounting, produce a capital-constrained Sharpe that (a) survives the multiple-testing correction for
the whole search and (b) holds on data never used for selection?

## Data and accounting (fixed)
- Pools: `purity_pairs_pit_k1` (1,375 pairs, entries only after the 1st BH-rejected window) and
  `purity_pairs_pit_k2` (267 pairs, after the 2nd). Both are arms; both count as trials.
- Trades: OLS hedge only (code review B4). Dollar P&L via `pnl_dollar.py` (hedge fixed at entry, real
  total-return leg prices, fixed notional, dollar costs). USD-only legs until FX conversion lands (disclosed;
  the search is re-run in full once it does — that re-run is a separate, labelled pass, not a new selection).
- Portfolio metric: `portfolio_sim.replay_portfolio(pnl_mode="dollar")`, $100,000, fixed sizing; business-day
  Sharpe (`portfolio_math`).
- Every configuration never opens a trade at or beyond its own stop (`ENTRY_ZSCORE_MAX` = stop level): a
  structural fix for code review B16, not a searched parameter.

## Grid (216 configurations per pool, 432 trials total)
| Parameter | Values |
|---|---|
| ENTRY_ZSCORE | 2.0, 2.5, 3.0 |
| stop rule | legacy abs(z) ≥ 3.5; directional @ 3.5; legacy @ 4.5 |
| re-entry re-arm | off, on |
| EXIT_ZSCORE | 0.0, 0.5 |
| MAX_HOLD_MULTIPLIER | 1, 2, 3 |
| entry gate | none, momentum |

## Splits (all four reported)
Calendar cutoff c(s) = t0 + s·(T − t0), t0 = the pool's earliest `eligible_from`, T = last data date, for
s ∈ {0.5, 0.6, 0.7, 0.8}. Development = entries before c(s); holdout = entries on/after c(s) + 1% embargo of
(T − t0). Trades entered before c(s) that exit after it are purged from both.

## Selection rule (per split, per pool)
Development period divided into 4 consecutive, equal calendar folds. Score = MEDIAN of the four fold
capital-sim Sharpes. Selected configuration = highest score (ties: fewer trades). Nothing else is tuned.

## Multiple-testing correction
- Deflated Sharpe (Bailey & López de Prado 2014) of the selected configuration's development Sharpe, with
  N = 432 and Var[SR] across all trials of that split.
- Probability of Backtest Overfitting via CSCV (Bailey, Borwein, López de Prado & Zhu 2017) on the matrix of
  development-period daily P&L, 16 blocks, all 12,870 combinations.

## Success criterion (declared now)
A configuration counts as a real signal only if, in EVERY one of the four splits: holdout capital-sim Sharpe
> 0, development DSR ≥ 0.95, and PBO < 0.20. Anything less is reported as "no robust signal found", with the
full table, including the best-looking holdout numbers labelled as not significant.

## Reported regardless of outcome
Full per-configuration table (development score, fold Sharpes, holdout Sharpe, n trades) for all 432 trials × 4
splits; the selected configuration per split/pool; DSR; PBO; the rank of the selected configuration on the
holdout among all configurations.

## Amendment 1 (2026-09-27, before ANY search result was evaluated)
The first launch was stopped at 140/432 runs with nothing evaluated (partial outputs set aside unread in
`output/research/strategy_search_ABORTED_stale_spreads_20260927/`), because the pool's spread series had been
built from the pre-fix yfinance cache (D1/D2) instead of CRSP total return. After regenerating them from WRDS
(`research/regenerate_pool_spread_series.py`), 110 pool "pairs" turned out to be one security under two labels
(identical daily returns on 100% of days, e.g. COST / PERMNO87055) — not pairs. Changes, made before any
result exists:
- Pools become `purity_pairs_pit_k1_clean` (1,265 pairs) and `purity_pairs_pit_k2_clean` (167 pairs).
- N for the DSR is 2 × 216 = 432 as before (same grid, same number of pool arms).
Nothing else changes.

## Amendment 2 (2026-09-28, before ANY result of the second pass exists)
This is the "separate, labelled pass" promised under *Data and accounting* (re-run once FX conversion lands). It is
run with the FIRST pass's outcome already known ("no robust signal found" in all 8 pool×split cells, Development.md
2026-09-27) — disclosed here, and both passes are reported side by side.
What changes, and why (all fixes committed before this amendment; details in docs/archive/audits/CODE_REVIEW_2026-09-26.md
"Data-layer round 3" and docs/archive/audits/INCONSISTENCY_SWEEP_2026-09-27.md):
- **Discovery is re-run from scratch** on the corrected data: coarse-bar stamps (D13), cross-asset labels (D16),
  WRDS ticker → security identity (D17: 2,719 reused tickers had been assigned to their oldest holder), corrupt
  WRDS files refetched (D19), loader dedupe that now also catches shorter-history aliases, FX-converted Compustat
  Global prices (R1.1). The chain is recorded with lineage (`research/pipeline_stages.py`) and no stage may resume
  from outputs made on the old data.
- **Pools are exactly what the re-run chain produces** (`purity_pairs_pit_k{1,2}_clean.parquet` from
  `research/clean_pool_identity_pairs.py`); no additional filtering or selection. Their sizes are reported as found.
- **Legs:** all legs priced in USD — CRSP legs as before, Compustat Global legs via `close_usd`. A trade whose legs
  lack a USD price at entry or exit is excluded and the count is reported (in the first pass ~69% of trades were
  excluded as non-USD). **Disclosed accounting asymmetry:** CRSP legs are total return (dividends included),
  Compustat Global legs are split-adjusted PRICE only (Compustat's `trfd` total-return factor has not been verified
  against real dividend events, data_wrds.py) — a pair with a Compustat leg omits that leg's dividends. If `trfd`
  is verified and applied before the second pass runs, this note is replaced by a dated addendum saying so.
- **Intraday discovery** runs without IBKR deep history (`include_ibkr=False`, Ross 2026-09-27), so 1h/4h pairs rest
  on yfinance's ~730-day intraday history only.
Unchanged: grid (216 configurations), both pool arms, N = 432 for the DSR, the four calendar splits and 1% embargo,
the median-of-four-folds selection rule, PBO via CSCV (16 blocks), and the success criterion.

## Amendment 2 addendum (drafted 2026-10-07; signed off by Ross 2026-10-10; committed before ANY result of the second pass exists)
No second-pass result exists: its pools have not been built and `research/strategy_search.py` has not been run on
corrected data. Known at commit time and disclosed: the discovery re-run's confirmed counts and the grid-phase
robustness result (items 3 and 5) -- discovery outputs, not strategy results. Changes since Amendment 2, each committed with a failing-first
test before this addendum (evidence: docs/archive/audits/INCONSISTENCY_SWEEP_2026-09-27.md, docs/ERRATA.md):
1. **Compustat Global legs are now total return** — the dated addendum Amendment 2 promised. `trfd` verified on real
   dividend events (HSBC, Toyota, BP 2024-25: the exact dividend on every ex-date, identical to price return to
   2e-16 otherwise; it captures HSBC's 2024-05 special dividend that `divd` omits) and applied to all 15,093
   listings. The accounting asymmetry disclosed in Amendment 2 no longer applies.
2. **D18: CRSP no-trade days are masked in discovery and quote-only series are excluded** (Ross, 2026-10-07, after
   both arms ran on identical data). The comparison (`research/d18_arm_comparison.py`) found 60 pairs confirmed by
   one arm only, 57 of them differing by window placement rather than the midpoint prices; no one-arm pair had a
   quote-only leg.
3. **Volume restated (DEV-003):** today's share units everywhere (CRSP cumulative price factor; Compustat `ajexdi`;
   7D–1Y files re-derived from the restated daily); a day or period with unknown volume is NaN, never 0. This changes
   the discovery scan's rolling-ADV liquidity gate, so **discovery was re-run once more**, also with the gate's price in
   USD (code review R1.2: Compustat Global `close` is local currency; the old gate passed 45.0% of international
   symbol-days at $25M instead of 9.0%). Run at code beb004b4, finished 2026-10-08: Tier 1 891, Tier 2 291, Tier 3 687
   confirmed. The 2026-10-05 run is superseded; its outputs are kept in a backup directory and not used.
4. **Pools:** what this re-run produces (offset-0 window grid), cleaned as in Amendment 2, plus items 7-9 below (each
   decided before this commit). No other filtering. Both pre-registered arms stay: k = 1 and k = 2 rejected windows.
5. **Grid-phase robustness (reported as a check, not as pool arms).** The scan was also run with its window grid
   shifted 63, 126 and 189 bars (definition fixed in `research/grid_phase_robustness.py` before any shifted run
   finished). Result, independently checked: 21.3% (Tier 2) / 17.6% (Tier 3) of offset-0 confirmations survive all four
   grids; the fragility is entirely in ONE-window confirmations -- pairs with >= 2 rejected windows are 82% / 94%
   grid-robust. Ross (2026-10-10): the robustness rule is the pre-registered k = 2 arm; the grid-robust share of each
   pool and of the traded pairs is reported beside the results. No extra pool arms, so **N stays at 432** (2 pools x
   216) and the success criterion is evaluated at 432 as declared.
6. **Known open issues this pass carries (disclosed, not fixed):** A2/A3 — where a rolling hedge ratio is missing the
   spread falls back to the full-sample ratio, and ratios are fitted through forward-filled outages (a causal arm
   exists but is not adopted); A4 — the rolling z-score window is derived from the full-sample half-life
   [**2026-10-19:** A2/A3 and A4 are fixed (89ececc4) and the Amendment-4 re-run's pool spreads are rebuilt on the
   fixed code (chain resumed from pool_spreads) -- results from that run do not carry them; earlier passes do]; B9 —
   same-bar fills. (B8, the engine's per-pair 20% holdout, does not apply: the search runs the engine with
   `holdout_only=False` and splits trades by the pre-registered calendar cutoffs, `strategy_search.split_trades`.) Point-in-time S&P 400/600 membership is not applied (disclosed
   limitation; source verification ongoing).
7. **Point-in-time eligibility (S32).** `eligible_from` = the end date of the pair's k-th window rejected under a BH
   family made only of windows concluded by that date (`episodic_bhfdr_confirm_asof`), not the whole-history family.
8. **Traded series consistent with D18 (S35).** The pool spreads mask CRSP no-trade (bid/ask-midpoint) days, as
   discovery does; no position is entered or marked on a price nobody traded at.
9. **Same-company pairs excluded (S36).** Pairs whose legs share a CRSP PERMCO (or Compustat GVKEY) -- share classes
   such as Z/ZG -- are removed at the pool step; the number removed is reported.
Unchanged: grid (216 configurations), the four calendar splits and 1% embargo, the median-of-four-folds selection
rule, PBO via CSCV (16 blocks), and the success criterion's thresholds (holdout Sharpe > 0, DSR ≥ 0.95, PBO < 0.20
in every split).

## Amendment 3 (approved by Ross 2026-10-12; committed before ANY result of the second pass exists)
The 2026-10-10 chain's second pass is void and was never reported: its run phase reused the FIRST pass's trade files
(BUG-D116; output moved to `output/research/strategy_search/_INVALID_20261011_reused_first_pass_trades/`). No valid
second-pass result exists at this commit; the re-run chain (`debug/_tmp_chain_rerun_20261012.sh`, started on CachyOS
2026-10-12 18:09) is at its first step. Known at commit time and disclosed: the per-label identity impact measurement
below (discovery-side, not a strategy result) and that the old pools contained 12 ADR-vs-home-listing pairs. Changes
since the Amendment 2 addendum, each committed with a failing-first test:
1. **Discovery re-run** (Tier 1-3 and intraday) on code with two fixes: BUG-D115 -- a CRASHED Engle-Granger test now
   enters BH's m with p = 1.0 (it was dropped, shrinking m); BUG-D117 -- the S&P 500 membership gate reads each file's
   content-verified PERMNO (`data_wrds.label_permno_map`; the old map named another security for 2,122 labels, 147 of
   which changed a gate decision; 0 confirmed pairs involved). 51 files whose volume had been restated with another
   security's split factors are re-restated. The 2026-10-08 discovery outputs are superseded (kept, not used).
2. **Same-company rule, completed (S36):** legs are the same company when their identifier sets intersect -- CRSP
   PERMCO (from the full names history, incl. ADRs), every GVKEY linked to it in the CRSP-Compustat link
   (crsp.ccmxpf_lnkhist, LC/LU/LS), and the Capital IQ company of its CUSIP or linked GVKEYs (ciq_common.wrds_cusip /
   wrds_gvkey; Capital IQ keeps one company id across a firm's listings). This removes ADR-vs-home-listing pairs
   (Toyota, Shell, Vodafone, HSBC, ...). The pool step refuses to run without these link files.
3. **D14: dual-listed twins excluded** -- pairs whose legs are the two parents of one dual-listed company
   (`research/dual_listed_companies.csv`: de Jong, Rosenthal & van Dijk 2009 Table I and later sources; identifiers in
   `research/dual_listed_companies_ids.csv`). They are one economic entity; kept as positive controls elsewhere.
4. **D15: pairs with an unverified leg excluded** -- a CRSP file whose security could not be identified from its
   content (85 files: too short to test, or no candidate's returns matched) does not enter a pool.
5. **Pool step order** (`research/clean_pool_identity_pairs.py`): identical-return pairs, same company, unverified leg,
   dual-listed twins -- each count reported. No other filtering; k = 1 and k = 2 arms unchanged.
6. **Run guards** (BUG-D116): each pool's trade directory carries the pool file's fingerprint; the run phase refuses
   trades built from another pool; the chain stops unless 216 fresh trade files per pool were written and the run took
   a plausible time.
Unchanged: everything else in Amendment 2 and its addendum -- grid (216 per pool, N = 432), splits, embargo,
selection rule, DSR/PBO, the success criterion, and the disclosed open issues (A2/A3, A4, B9).

## Amendment 4 (approved by Ross 2026-10-15; committed before ANY result of the re-run below exists)
The Amendment 3 second pass ran (2026-10-14, 0 of 8 cells pass) and was independently reviewed (verdict held; "k = 2
is a lead" judged overstated). Before its result is registered, a data defect was found and fixed, so the pass is
RE-RUN under this amendment; the 2026-10-14 output is kept and reported as superseded, never as the result.
1. **BUG-D118, Compustat Global prices.** 698 of 15,094 series had ~1000x one-day level jumps (in 136 of 680 Tier-3
   confirmations; 29% of the k = 2 pool). (a) Prices are quoted per `qunit` shares; per-share price is now
   prccd / (qunit x ajexdi) at fetch, and 104 cached series were repaired. (b) Any remaining one-day move > 5x in a
   Compustat Global total-return series splits the series there (bad prints that revert within 5 trading days are
   masked instead); the earlier pieces become separate `<label>_segN` series of the same company; 20 residual
   fragments are quarantined. After the fix no Compustat Global daily series has a one-day move > 5x.
2. **Structural pairs excluded at the pool step** (production's index-tracking and share-class whitelists; SPY/VOO@1h
   had reached the k = 2 pool).
3. **Disclosed deviations in the evaluation, unchanged for comparability with passes 1-2:** the DSR uses the selected
   configuration's unconstrained development daily Sharpe (selection uses capital-sim fold Sharpes), and Var[SR] is
   taken across the 216 trials of one pool while N = 432.
Discovery, intraday, pools and the search are re-run in full (`debug/_tmp_chain_rerun_20261012.sh`). Unchanged:
everything else in Amendments 2-3 -- grid (N = 432), splits, embargo, selection rule, DSR/PBO, success criterion.

## Amendment 5 (approved by Ross 2026-10-21, DECISIONS_2026-10-21 #1-2; committed before ANY result of the re-run below exists)
The Amendment 4 re-run completed 2026-10-20 (0 of 8 cells pass). Its independent review (2026-10-21) held the verdict
and found two defects, both of which make results look better (ERRATA): BUG-D119, a trade booked across an 810-day
hole in one leg's prices that carries most of k = 2's holdout positivity, and BUG-D120, pool membership from one BH
over the whole window family. The sealed holdout had also not been enforced in code (eval fixed 2026-10-20). The
Amendment 4 result is reported as superseded, never as the result. Changes, each with a failing-first test:
1. **Unrealizable trades (BUG-D119).** A trade during which either leg has no valid price (close and total return
   finite, > 0) for more than 5 business days (data._MAX_FILL_BARS, the DATA_GAP rule) -- counted from the leg's last
   valid bar at or before entry to the exit date, so a stale entry or exit price counts -- gets pnl status
   `unrealizable_gap`: excluded from P&L and COUNTED per pool and configuration
   (`strategy_search/trade_status_counts.parquet`, printed in the eval log). Disclosed: the excluded trades' outcomes
   are unknowable; positions caught in a halt or delisting often lose, so excluding them can flatter the result.
   `debug/_verify_pnl_unrealizable_gap_d119.py`.
2. **BUG-D118 rule on consecutive valid prices.** The > 5x split rule compares consecutive VALID prices (a NaN hole
   hid GVKEY015736's 175.88 -> 11.56). Every Compustat Global label is re-segmented from its original series
   (`_pre_split_backup` where one exists), pre-seal rows only; stale `_segN` files are removed; files still holding a
   > 5x move are quarantined (`output/cache/wrds/_quarantine_d118_a5/`, Amendment 4 moved its 20 by hand) and the
   chain stops unless 0 remain. `debug/_verify_split_level_breaks.py`.
3. **The pool is the point-in-time-eligible set (BUG-D120).** Per timeframe, every pair with >= k rejections under
   the as-of BH family at some month-end (`purity_pit_eligibility.build_pit_pool`), windows ending before the seal
   of their timeframe only. Membership no longer passes through the whole-history rejection set; its pairs are
   flagged (`in_whole_history_set`). Cleaning unchanged (Amendment 3 order, Amendment 4 structural exclusions);
   arms reported separately (S31 (c)). `debug/_verify_pit_pool_membership_d120.py`.
4. **Sealed holdout enforced at the data layer** (`seal.py`, DECISIONS_2026-10-21 #2). No live price cache holds a
   sealed row: writers route sealed rows to `output/cache/_sealed_vault/`, a sweep moves any already there, shared
   readers drop them as a backstop, and the chain stops unless the audit counts 0. Daily-and-coarser data is sealed
   from 2026-01-01; intraday from 2026-10-21 (all yfinance intraday is 2024+; its holdout is forward-recorded bars).
   The search's evaluation span still ends 2025-12-31 for EVERY timeframe (`seal_trades`): its splits are calendar
   fractions of one common span. Disclosed: the 2026 Compustat Global and January-August 2026 intraday data were
   already used by the Amendment 4 run and its discovery, so they cannot serve as an untouched holdout.
   `debug/_verify_seal_data_layer.py`.
Discovery, intraday, adapter, pools, spreads and the search are re-run in full (`debug/_tmp_chain_a5_20261021.sh`).
Unchanged: everything else in Amendments 2-4 -- grid (216 per pool, N = 432), splits, embargo, selection rule,
DSR/PBO, success criterion, and the disclosed evaluation deviations of Amendment 4 item 3.

### Amendment 5 addendum (2026-10-21, after an independent review of the Amendment 5 code; committed before ANY result of the re-run exists -- the chain is in its discovery step)
Implementation corrections, each with a failing-first test; the rules above are unchanged except where stated:
- **Counting (item 1).** The engine drops unpriceable trades before the trade file is saved
  (backtest.apply_pnl_basis), so counting the saved files alone would have reported zero unrealizable trades. The
  run phase now saves every dropped trade (`strategy_search/<pool>/_dropped/<config>.parquet`) and the eval counts
  them with the kept ones; a missing log is reported as its own status, never as zero. `_verify_strategy_search.py`
  13/14 -> 15/15 (engine-level check).
- **Hole count (item 1).** The exit date counts as missing when it has no valid bar (the count was one day short), and
  the hole check runs before the price lookups, so a stale entry or exit price is `unrealizable_gap` on both the daily
  and intraday paths (it was `missing_price` intraday). `_verify_pnl_unrealizable_gap_d119.py` 9/11 -> 11/11.
- **Spreads.** A pair whose spread series cannot be rebuilt is left without one and reported; the pre-run file (built
  from the previous data) is no longer restored. `_verify_regenerate_no_restore.py`.
- **Seal (item 4).** FRED and CFTC COT caches and their fresh fetches are sealed too (regime inputs); two fetch scripts
  that wrote WRDS price files directly now go through the seal writer. Column-dated reference data (Compustat
  fundamentals, IBES, Fama-French factors) is not sealed by this mechanism and is not used by the search.
- **Disclosed, not changed:** the 5-day rule counts weekdays, so an exchange closure longer than five weekdays (Lunar
  New Year on some Asian listings: 6-7) counts as a hole, as it already does for backtest.py's B1 exit (proposal to
  Ross pending, see the decision log); pool metadata from the whole-history file is joined only where the pair's
  orientation matches.
