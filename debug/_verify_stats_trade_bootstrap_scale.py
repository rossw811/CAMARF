"""
Regression test for code review S13 (verified 2026-10-07, fixed the same day): stats.run_montecarlo Phase 2 bootstrapped
PER-TRADE P&L and scored each resample with _portfolio_sharpe, which multiplies by sqrt(252) as if every trade were a
trading day -- an annualized number only if the strategy closes exactly 252 trades a year. Not consumed or cited
anywhere (grep 2026-10-07). Fix: report the per-trade Sharpe (mean / sd per trade, not annualized) under columns that
say so (sim_trade_sharpe_5pct / _median / _95pct).
Checks: synthetic trades with per-trade mean 2, sd 4 (per-trade Sharpe 0.5): the bootstrap median is ~0.5 (not
~7.9 = 0.5*sqrt(252)); the old column names are gone.
Run: python debug/_verify_stats_trade_bootstrap_scale.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import stats

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    rng = np.random.default_rng(0)
    n = 2000
    t = pd.bdate_range("2015-01-02", periods=n)
    pnl = rng.normal(2.0, 4.0, n)
    tr = pd.DataFrame({"symbol_a": "A", "symbol_b": "B", "tf": "1D", "exit_time": t,
                       "entry_time": t - pd.Timedelta(days=2), "pnl_net": pnl})
    res = stats.run_montecarlo(tr, stats._build_daily_pnl(tr))
    rb = res.get("regime_bootstrap")
    check("has_regime_bootstrap", isinstance(rb, pd.DataFrame) and len(rb) > 0)
    if isinstance(rb, pd.DataFrame) and len(rb):
        col = "sim_trade_sharpe_median"
        med = float(rb[col].iloc[0]) if col in rb.columns else np.nan
        target = float(np.mean(pnl) / np.std(pnl))
        check("per_trade_scale", np.isfinite(med) and abs(med - target) < 0.05, f"{med:.3f} vs {target:.3f}")
        check("old_annualized_columns_gone", "sim_sharpe_median" not in rb.columns, list(rb.columns))
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
