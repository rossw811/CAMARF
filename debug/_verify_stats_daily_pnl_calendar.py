"""
Regression test for code review S9 (verified 2026-10-07, fixed the same day): stats._build_daily_pnl grouped trades
by exit date only, so days with no exit were missing rather than zero -- run_montecarlo's Phase 3 slippage Sharpe
(and the DCC-GARCH input) came from an exit-days-only series (BUG-D62/D64 class: inflated Sharpe, compressed time).
Fix: every business day from the first to the last exit, zero where nothing exited -- the calendar
portfolio_math.daily_pnl_from_exits uses.
Checks: 10 exits spread over 100 business days -> 100 rows, 90 of them zero, sums unchanged, one column per pair;
the summed series equals portfolio_math.daily_pnl_from_trades on the same trades (same calendar).
Run: python debug/_verify_stats_daily_pnl_calendar.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import portfolio_math
import stats

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    days = pd.bdate_range("2021-01-04", periods=100)
    pick = days[::11][:10]
    rng = np.random.default_rng(0)
    tr = pd.DataFrame({"symbol_a": ["A", "C"] * 5, "symbol_b": ["B", "D"] * 5, "tf": "1D",
                       "exit_time": pick, "pnl_net": rng.normal(10, 5, 10)})
    d = stats._build_daily_pnl(tr)
    expect_days = len(pd.bdate_range(pick.min(), pick.max()))
    check("all_business_days", len(d) == expect_days, f"{len(d)} vs {expect_days}")
    check("zero_on_no_exit_days", int((d.sum(axis=1) == 0).sum()) == expect_days - 10)
    check("sum_unchanged", np.isclose(d.values.sum(), tr["pnl_net"].sum()))
    check("one_column_per_pair", d.shape[1] == 2)
    pm = portfolio_math.daily_pnl_from_trades(tr)
    tot = d.sum(axis=1)
    check("same_calendar_as_portfolio_math", tot.index.equals(pm.index) and np.allclose(tot.values, pm.values),
          f"{len(tot)} vs {len(pm)}")
    # (stats._portfolio_sharpe uses population sd, portfolio_math sample sd: a sqrt(n/(n-1)) difference, logged
    #  separately in docs/bug_recheck/manual_verdicts.csv, not part of S9)
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
