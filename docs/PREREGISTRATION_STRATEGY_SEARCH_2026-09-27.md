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
