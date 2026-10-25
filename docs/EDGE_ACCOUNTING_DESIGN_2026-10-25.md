# Edge accounting: design (Ross approved 2026-10-25, "approve, yes to all")

Committed before any result exists. Question: of the gap between the pipeline as originally run and the corrected
pipeline, how much does each identified error account for? Descriptive attribution on development data only (every
row before `Config.DATA.SEALED_FROM` / `SEALED_FROM_INTRADAY`); not a test of the strategy and never a decision input.

## Factors (2 x 2 x 2 full factorial, 8 cells per pool)

| Factor | Old ("error present") | Corrected |
|---|---|---|
| S. Pair selection | whole-history pool (`purity_pairs.parquet`, BH over each pair's whole history), no `eligible_from` gate, spreads built with window lengths from the full sample (`eligible_from=None`) | PIT pool (`purity_pairs_pit_k{k}_clean.parquet`), entries only from `eligible_from`, spreads from formation bars only (the production files) |
| P. P&L basis | spread-unit P&L with the hedge ratio re-estimated every bar and dollar costs mixed into log units (`pnl_legacy_net`), per unit gross notional: `pnl_legacy_net / n_shares_a / (1 + abs(hedge_ratio))` | dollar P&L, position fixed at entry, legs at total-return prices (`pnl_dollar.add_dollar_pnl`): `pnl_dollar_net / notional_dollar_entry` |
| X. Executability | trades spanning a hole of more than 5 trading days in either leg are kept (and, under P corrected, priced across the hole: `check_holes=False`) | dropped (`unrealizable_gap`, BUG-D119, Amendment 5) |

k = 1 and k = 2: the whole-history pool is restricted to pairs with at least k whole-history BH-rejected windows and
cleaned by the same rules as the PIT pools (identity, same company, unverified leg, dual-listed twins, structural).

Not a factor: the D118 split fix (price level breaks). The data were rebuilt and the pre-fix series no longer exist,
so every cell uses corrected prices; the split fix's contribution is not measured here and is disclosed as such.

## Held fixed

- One configuration: production defaults (`Config.BACKTEST` as of this commit), OLS hedge, regime/ML layers off.
  Not selected from the strategy search, so no selection enters the attribution.
- One trade set per selection arm: the engine runs once per arm with legacy P&L (every trade kept), and the P and X
  cells are computed on those same trades. All cells are restricted to trades the dollar basis can price apart from
  holes (status `ok` or `unrealizable_gap`): trades with no USD price, missing prices or a bad hedge exist only under
  the legacy basis, and keeping them would mix a coverage change into factor P. Their count is reported.

## Metric

Equal-notional book: each trade is one unit of gross notional; the day's return is the sum of the returns of the
trades exiting that business day (zero on days with no exit), over the pool's development period. Reported per cell:
annualised Sharpe (sqrt 252), number of trades, mean trade return. The capital-constrained ($100k) simulation is
reported for the two dollar-basis corner cells only (it cannot price legacy trades consistently; portfolio_sim's
legacy mode skips legs with no price).

## Attribution

Shapley value of each factor on the Sharpe: the average, over the 6 orderings of S, P, X, of the change when that
factor is corrected. Exact from the 8 cells; the three values sum to Sharpe(all corrected) - Sharpe(all old). Also
reported: each factor corrected alone from the all-old cell, and the forward order S -> P -> X.

Uncertainty: stationary block bootstrap over business days (mean block = the Politis-White estimate on the all-old
cell's daily series, rounded), 2,000 draws, the same day indices applied to all 8 cells in a draw, so each Shapley
value gets a percentile 95% interval.

## Outputs

`output/research/edge_accounting_k{k}.parquet` (cells), `edge_accounting_shapley_k{k}.parquet`; script
`research/edge_accounting.py`; synthetic check `debug/_verify_edge_accounting.py` written and failing before the
script. Whole-history spreads go to `output/results_wholehistory/` (never the production `output/results/`).
