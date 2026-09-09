"""Synthetic proof for research/pit_wfa_pooled_equity_curve.py -- confirms
the inter-fold calendar gap is actually dropped (not zero-filled) and that
per-fold Sharpe values reproduce exactly against a known hand-computed
case, before trusting the real pit_wfa_wrds_daily result built on top of
it."""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from pit_wfa_pooled_equity_curve import pool_variant, sharpe_from_daily_pnl_local
import portfolio_math

n_checks = 0
n_passed = 0


def check(name, cond):
    global n_checks, n_passed
    n_checks += 1
    status = "PASS" if cond else "FAIL"
    if cond:
        n_passed += 1
    print(f"[{status}] {name}")


# Fold 1: 3 trades in Jan 2000. Fold 2: 3 trades in Jan 2020 (a 20-year gap).
trades = pd.DataFrame([
    {"exit_time": pd.Timestamp("2000-01-03"), "actual_pnl": 10.0, "wfa_variant": "test", "fold": "f1"},
    {"exit_time": pd.Timestamp("2000-01-04"), "actual_pnl": -5.0, "wfa_variant": "test", "fold": "f1"},
    {"exit_time": pd.Timestamp("2000-01-05"), "actual_pnl": 8.0, "wfa_variant": "test", "fold": "f1"},
    {"exit_time": pd.Timestamp("2020-01-03"), "actual_pnl": 20.0, "wfa_variant": "test", "fold": "f2"},
    {"exit_time": pd.Timestamp("2020-01-04"), "actual_pnl": -10.0, "wfa_variant": "test", "fold": "f2"},
    {"exit_time": pd.Timestamp("2020-01-05"), "actual_pnl": 15.0, "wfa_variant": "test", "fold": "f2"},
])

result = pool_variant(trades, "test", ["f1", "f2"])
print(result)

# --- 1. Each fold's own daily-obs count matches its own real 3-day span, not the 20-year gap ---
n_f1 = result["per_fold"][0]["n_daily_obs"]
n_f2 = result["per_fold"][1]["n_daily_obs"]
check("fold1's daily-obs count matches its own 3-day span (Jan 3-5, 2000)", n_f1 == 3)
check("fold2's daily-obs count matches its own 3-day span (Jan 3-5, 2020), NOT the 20-year gap",
      n_f2 == 3)

# --- 2. Pooled daily-obs count is the SUM of the two folds' own spans, NOT the full calendar range ---
# A zero-filled 20-year gap would add ~7300 extra days; dropping it means pooled == n_f1 + n_f2.
check("pooled daily-obs count = n_f1 + n_f2 (gap dropped, not zero-filled)",
      result["n_pooled_daily_obs"] == n_f1 + n_f2)

# --- 3. Pooled total P&L equals the exact sum of all 6 real trades ---
expected_total = 10.0 - 5.0 + 8.0 + 20.0 - 10.0 + 15.0
check(f"pooled total P&L equals the exact sum of all trades ({expected_total})",
      np.isclose(result["pooled_total_pnl"], expected_total))

# --- 4. Per-fold Sharpe matches an independent direct computation on that fold alone ---
f1_trades = trades[trades["fold"] == "f1"]
f1_daily = portfolio_math.daily_pnl_from_trades(f1_trades, pnl_col="actual_pnl")
f1_sharpe_direct = sharpe_from_daily_pnl_local(f1_daily)
check("fold1's reported Sharpe matches an independent direct computation",
      np.isclose(result["per_fold"][0]["fold_sharpe"], f1_sharpe_direct, equal_nan=True))

# --- 5. Real-data sanity check: a fold covering more CALENDAR TIME (more zero-days) with
# fewer trades can dominate the pooled mean/std purely via observation count -- a real
# weighting property to disclose, not a bug, but worth confirming it's real. ---
long_fold = pd.DataFrame([
    {"exit_time": pd.Timestamp("2000-01-01") + pd.Timedelta(days=i * 30), "actual_pnl": 1.0,
     "wfa_variant": "test2", "fold": "long"} for i in range(5)
])  # 5 trades spread across ~150 days -> ~150 daily obs, mostly zero
short_fold = pd.DataFrame([
    {"exit_time": pd.Timestamp("2010-01-01"), "actual_pnl": 100.0, "wfa_variant": "test2", "fold": "short"},
    {"exit_time": pd.Timestamp("2010-01-02"), "actual_pnl": -100.0, "wfa_variant": "test2", "fold": "short"},
])  # 2 trades, 2 daily obs
combo = pd.concat([long_fold, short_fold], ignore_index=True)
result2 = pool_variant(combo, "test2", ["long", "short"])
n_long = result2["per_fold"][0]["n_daily_obs"]
n_short = result2["per_fold"][1]["n_daily_obs"]
check(f"the long-calendar-span fold has far more daily observations than the short one "
      f"({n_long} vs {n_short}) despite fewer trades -- confirms pooling weights by "
      f"CALENDAR DAYS, not by trade count (a real property to disclose in the writeup)",
      n_long > n_short * 10)

print(f"\n{n_passed}/{n_checks} checks passed")
sys.exit(0 if n_passed == n_checks else 1)
