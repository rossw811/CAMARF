"""
CAMARF portfolio_effective_bets.py — comparison/diagnostic method, NOT part
of the production pipeline.

Extends research/dd_hub_effective_bets.py's three effective-bet-count methods
(Grinold-Kahn breadth, Meucci ENB, Carver IDM — imported directly, not
reimplemented) from the 5-pair DD-hub cluster to the FULL confirmed-pair
portfolio (Ross, 2026-07-06). Answers: across all confirmed pairs (any TF,
any hedge method), how many genuinely independent bets does the live
portfolio actually represent, once cross-pair exit-timing/regime correlation
is accounted for?

Directly motivated by tonight's permutation-test fix (stats.py BUG-D53,
Development.md Session 27 addendum): 296 OOS trades collapsed into just 70
unique exit-days, 66/70 with >1 trade, up to 28 on a single day — the same
correlated-exposure mechanism the DD-hub work already flagged for one small
cluster. This script checks whether that's a portfolio-wide effect, not just
a DD-hub-specific one.

Method: build each confirmed pair's own daily P&L series (from
output/backtest/trades_layer1*.parquet, hedge_method="ols" — the project's
primary/baseline method, so each pair is counted once, not once per hedge
method), aligned on the union of all trading days (0 P&L on days a given
pair had no trade — the natural convention for a multi-strategy correlation
matrix, not NaN/dropna, which would need pairs to share EVERY active day).
Correlation matrix over that daily P&L panel feeds the same three methods.

Read-only. Never fetches, never recomputes hedge ratios or spreads.

Usage:
    python research/portfolio_effective_bets.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research.dd_hub_effective_bets import (
    grinold_kahn_breadth,
    meucci_effective_bets,
    carver_idm,
    analyze_cluster,
)

_BACKTEST_DIR = os.path.join("output", "backtest")
_HEDGE_METHOD = "ols"  # primary/baseline method — avoids double-counting each pair per method


def _load_trades(suffix: str) -> pd.DataFrame:
    path = os.path.join(_BACKTEST_DIR, f"trades_{suffix}.parquet")
    if not os.path.exists(path):
        return pd.DataFrame()
    return pd.read_parquet(path)


def build_daily_pnl_panel(trades: pd.DataFrame) -> pd.DataFrame:
    """
    Returns a wide DataFrame: index = calendar date (union across all pairs),
    columns = "{symbol_a}/{symbol_b}@{tf}", values = that pair's net P&L
    summed for trades exiting on that date, 0.0 on days with no exit.
    """
    tr = trades[trades["hedge_method"] == _HEDGE_METHOD].copy()
    if tr.empty:
        return pd.DataFrame()
    tr["exit_date"] = pd.to_datetime(tr["exit_time"]).dt.date
    tr["pair_key"] = tr["symbol_a"] + "/" + tr["symbol_b"] + "@" + tr["tf"].astype(str)

    daily_by_pair = {}
    for pair_key, group in tr.groupby("pair_key"):
        daily_by_pair[pair_key] = group.groupby("exit_date")["pnl_net"].sum()

    panel = pd.DataFrame(daily_by_pair).fillna(0.0)
    return panel.sort_index()


def main():
    trades_is = _load_trades("layer1")
    trades_oos = _load_trades("layer1_holdout")
    all_trades = (
        pd.concat([trades_is, trades_oos], ignore_index=True)
        if len(trades_is) > 0 else trades_oos
    )
    if all_trades.empty:
        print("No trades found in output/backtest/ — run backtest.py first.")
        return

    panel = build_daily_pnl_panel(all_trades)
    n_pairs = panel.shape[1]
    print(f"Loaded {len(all_trades)} trades ({_HEDGE_METHOD} hedge method), "
          f"{n_pairs} confirmed pairs, {len(panel)} unique active days\n")

    if n_pairs < 3:
        print("Fewer than 3 pairs with trades — effective-bets methods need a "
              "meaningful correlation matrix (need >=3). Skipping.")
        return

    corr_matrix = panel.corr().to_numpy()
    corr_matrix = np.nan_to_num(corr_matrix, nan=0.0)
    np.fill_diagonal(corr_matrix, 1.0)

    print("Per-pair correlation matrix (daily P&L, OLS hedge method):")
    print(panel.corr().round(2).to_string())
    print()

    result = analyze_cluster(corr_matrix)
    print(f"N pairs: {result['n']}")
    print(f"Average pairwise correlation (rho_bar): {result['rho_bar']:.4f}")
    print(f"Grinold-Kahn effective breadth (BR_eff): {result['grinold_kahn_breadth']:.3f}")
    print(f"Meucci Effective Number of Bets (ENB):   {result['meucci_enb']:.3f}")
    print(f"Carver Instrument Diversification Multiplier (IDM): {result['carver_idm']:.3f}")
    print(f"  (check: IDM^2 = {result['idm_squared_vs_breadth_check']:.3f}, "
          f"should equal BR_eff = {result['grinold_kahn_breadth']:.3f} under equal weighting)")
    print(f"\nNominal pair count: {n_pairs}  vs.  effective independent bets: "
          f"~{result['grinold_kahn_breadth']:.1f} (Grinold-Kahn) / "
          f"~{result['meucci_enb']:.1f} (Meucci)")

    # Flag the highest-correlation pair clusters — which specific pairs are
    # driving the diversification loss, not just the aggregate number.
    off_diag = panel.corr().where(~np.eye(n_pairs, dtype=bool))
    top_corr = (
        off_diag.stack()
        .rename("corr")
        .reset_index()
        .rename(columns={"level_0": "pair_a", "level_1": "pair_b"})
    )
    top_corr = top_corr[top_corr["pair_a"] < top_corr["pair_b"]]  # dedup symmetric pairs
    top_corr = top_corr.reindex(top_corr["corr"].abs().sort_values(ascending=False).index)
    print("\nTop 10 highest |correlation| pair-pairs (candidates for the diversification loss):")
    print(top_corr.head(10).to_string(index=False))

    os.makedirs("output/research", exist_ok=True)
    pd.DataFrame([result]).to_parquet("output/research/portfolio_effective_bets.parquet")
    panel.corr().to_parquet("output/research/portfolio_effective_bets_corr_matrix.parquet")
    print("\nWrote output/research/portfolio_effective_bets.parquet "
          "and portfolio_effective_bets_corr_matrix.parquet")


if __name__ == "__main__":
    main()
