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
What changes, and why (all fixes committed before this amendment; details in docs/CODE_REVIEW_2026-09-26.md
"Data-layer round 3" and docs/INCONSISTENCY_SWEEP_2026-09-27.md):
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
test before this addendum (evidence: docs/INCONSISTENCY_SWEEP_2026-09-27.md, docs/ERRATA.md):
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
   exists but is not adopted); A4 — the rolling z-score window is derived from the full-sample half-life; B9 —
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
