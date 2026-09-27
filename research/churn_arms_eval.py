"""
research/churn_arms_eval.py -- score the 2026-09-27 churn-loop / dead-code-pathway comparison arms.

For each arm file in output/research/churn_arms_2026-09-27/{arm}_{is|oos}.parquet (written by the launch
script, momentum gate on the Purity pool): OLS rows only (B4), dollar P&L via pnl_dollar.py (B2/B3; USD-only
legs), business-day Sharpe (P1), and the rule-invariant counts from research/strategy_rule_invariants.py.
"""
import glob
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pnl_dollar
import portfolio_math as pm
from config import Config
from research.strategy_rule_invariants import check_trade_invariants


def main():
    B = Config.BACKTEST
    P = dict(ENTRY_ZSCORE=B.ENTRY_ZSCORE, STOP_ZSCORE=B.STOP_ZSCORE, EXIT_ZSCORE=B.EXIT_ZSCORE,
             MAX_HOLD_MULTIPLIER=B.MAX_HOLD_MULTIPLIER, MIN_HALF_LIFE_BARS=B.MIN_HALF_LIFE_BARS)
    rows = []
    for f in sorted(glob.glob("output/research/churn_arms_2026-09-27/*.parquet")):
        name = os.path.basename(f)[:-8]
        arm, split = name.rsplit("_", 1)
        T = pd.read_parquet(f)
        T = T[T["hedge_method"] == "ols"]
        inv = check_trade_invariants(T, P)["counts"]
        D = pnl_dollar.add_dollar_pnl(T)
        ok = D[D["pnl_dollar_status"] == "ok"]
        rows.append({"arm": arm, "split": split, "n_trades_ols": len(T), "n_usd": len(ok),
                     "dollar_net_sharpe": pm.sharpe_from_trades(ok, "pnl_dollar_net"),
                     "dollar_gross_sharpe": pm.sharpe_from_trades(ok, "pnl_dollar_gross"),
                     "dollar_net_sum": ok["pnl_dollar_net"].sum(), "win_rate": (ok["pnl_dollar_net"] > 0).mean(),
                     "median_hold": T["hold_bars"].median(),
                     "entries_past_stop_pct": 100 * inv["I2_entry_at_or_past_stop"] / max(len(T), 1),
                     "favorable_stops_pct": 100 * inv["S1_stop_after_favorable_move"] / max(len(T), 1),
                     "reentry_after_stop_pct": 100 * inv["S3_reentry_within_1_bar_of_stop"] / max(len(T), 1),
                     "exit_reasons": T["exit_reason"].value_counts().to_dict()})
    R = pd.DataFrame(rows).sort_values(["split", "arm"])
    pd.set_option("display.width", 250)
    print(R.drop(columns=["exit_reasons"]).round(3).to_string(index=False))
    for r in R.itertuples():
        print(f"{r.arm:28s} {r.split:3s} exits {r.exit_reasons}")
    R.to_parquet("output/research/churn_arms_eval.parquet")


if __name__ == "__main__":
    main()
