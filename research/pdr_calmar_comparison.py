"""
research/pdr_calmar_comparison.py -- comparison/diagnostic method, NOT part of the production
pipeline (task #49, 2026-07-13/14).

Ross's framing: the best Sharpe isn't the priority for the live strategy -- P&L at a manageable
drawdown matters more, reported as PDR (Profit-to-Drawdown Ratio = Profit Factor / Max Drawdown %)
and the standard Calmar Ratio (Annualized Return / Max Drawdown %), compared against the existing
Sharpe-based sizing-method rankings to see whether the ranking changes under a drawdown-focused
lens. Verified first: debug/_verify_pdr_calmar.py, 3/3 synthetic cases pass.

Usage:
    python research/pdr_calmar_comparison.py [--account-size 100000] [--trades-path ...]
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from portfolio_sim import (
    replay_portfolio, portfolio_sharpe_from_replay, max_drawdown_pct,
    profit_factor_from_replay, pdr_from_replay, calmar_from_replay,
)

SIZING_METHODS = ["fixed", "equity_proportional", "flat_2pct",
                  "quarter_kelly", "third_kelly", "half_kelly", "full_kelly"]


def main():
    p = argparse.ArgumentParser(description="PDR/Calmar vs. Sharpe ranking comparison across sizing methods")
    p.add_argument("--account-size", type=float, default=100_000)
    p.add_argument("--trades-path", default="output/backtest/trades_layer1.parquet")
    args = p.parse_args()

    trades_df = pd.read_parquet(args.trades_path)
    trades_df["entry_time"] = pd.to_datetime(trades_df["entry_time"])
    trades_df["exit_time"] = pd.to_datetime(trades_df["exit_time"])
    print(f"Loaded {len(trades_df)} trades from {args.trades_path}, "
          f"account size ${args.account_size:,.0f}\n")

    rows = []
    for method in SIZING_METHODS:
        result = replay_portfolio(trades_df, args.account_size, method)
        sharpe = portfolio_sharpe_from_replay(result)
        dd = max_drawdown_pct(result["equity_curve"])
        pf = profit_factor_from_replay(result)
        pdr = pdr_from_replay(result)
        calmar = calmar_from_replay(result)
        rows.append({
            "sizing_method": method,
            "n_taken": result["n_taken"],
            "skipped": result["skipped_count"],
            "final_equity": result["final_equity"],
            "sharpe": sharpe,
            "max_dd_pct": dd,
            "profit_factor": pf,
            "pdr": pdr,
            "calmar": calmar,
        })

    df = pd.DataFrame(rows)
    print(df.to_string(index=False, float_format=lambda x: f"{x:,.4f}"))

    print("\n--- Ranking comparison: does the #1 sizing method change by metric? ---")
    for metric in ["sharpe", "pdr", "calmar"]:
        ranked = df.sort_values(metric, ascending=False)
        top = ranked.iloc[0]
        print(f"  Best by {metric:>8}: {top['sizing_method']:<20} "
              f"({metric}={top[metric]:.4f}, max_dd={top['max_dd_pct']:.4f})")

    out_path = "output/research/pdr_calmar_comparison.parquet"
    df.to_parquet(out_path)
    print(f"\nSaved -> {out_path}")


if __name__ == "__main__":
    sys.exit(main())
