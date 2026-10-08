"""
Regression test for code review R5.1 (found STILL OPEN by the 2026-10-07 independent check, fixed the same day):
research/pit_wfa_pooled_equity_curve.py built each fold's daily P&L with portfolio_math.daily_pnl_from_trades WITHOUT
the fold's test window, so zero-filling ran only from the fold's first to last exit -- trade-free days at the fold's
edges were dropped, inflating the pooled Sharpe. The helper gained start/end on 2026-09-26 (85e766fb) but no caller
passed them. Fix: research/pit_wfa_wrds_daily.py tags each fold's taken trades with test_start/test_end, and the
pooling script zero-fills over [test_start, test_end]; trades without the window are refused (re-run the producer),
never silently pooled on the exit span.
Checks: a fold whose test window is 100 business days with 5 exits in the middle -> 100 daily rows; missing window
columns -> ValueError; the producer writes test_start/test_end (source check).
Run: python debug/_verify_pooled_equity_fold_window.py
"""
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import research.pit_wfa_pooled_equity_curve as m

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    days = pd.bdate_range("2022-01-03", periods=100)
    tr = pd.DataFrame({"exit_time": days[40:45], "actual_pnl": [10.0, -5, 7, 3, 1], "wfa_variant": "v",
                       "fold": "f1", "test_start": days[0], "test_end": days[-1]})
    res = m.pool_variant(tr, "v", ["f1"])
    check("fold_window_zero_filled", res["n_pooled_daily_obs"] == 100, res["n_pooled_daily_obs"])
    check("pnl_unchanged", np.isclose(res["pooled_total_pnl"], 16.0))
    try:
        m.pool_variant(tr.drop(columns=["test_start", "test_end"]), "v", ["f1"])
        check("missing_window_refused", False)
    except ValueError:
        check("missing_window_refused", True)
    src = open(os.path.join(ROOT, "research", "pit_wfa_wrds_daily.py"), encoding="utf-8").read()
    check("producer_writes_window", 'fold_taken["test_start"]' in src and 'fold_taken["test_end"]' in src)
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
