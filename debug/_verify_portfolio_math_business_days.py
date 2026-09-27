"""
Regression test for code-review finding P1 (2026-09-26): portfolio_math.daily_pnl_from_exits
resampled to CALENDAR days (weekends inserted as 0) while sharpe_from_daily_pnl annualizes with
sqrt(252) (trading days), and zero-filled only between the first and last exit, dropping genuine
no-trade days at the edges of an evaluation window (R5.1: pooled WFA Sharpe inflated).

Checks:
  1. the daily series has one row per BUSINESS day, no Saturday/Sunday rows;
  2. with start/end given, it spans the whole window, zero-filled at both edges;
  3. hand-computed Sharpe on a known business-day series.

Run: python debug/_verify_portfolio_math_business_days.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import portfolio_math as pm

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    # Exits on Fri 2026-03-06 and Mon 2026-03-09 -> business days only: Fri, Mon (2 rows), not 4.
    exits = [pd.Timestamp("2026-03-06 16:00"), pd.Timestamp("2026-03-09 16:00")]
    s = pm.daily_pnl_from_exits(exits, [10.0, -4.0])
    check("bday.no_weekend_rows", not any(d.dayofweek >= 5 for d in s.index), f"index={list(s.index.date)}")
    check("bday.two_rows", len(s) == 2, f"len={len(s)}")
    check("bday.values", list(s.to_numpy()) == [10.0, -4.0])

    # Window 2026-03-02 (Mon) .. 2026-03-13 (Fri) = 10 business days, exits only on 03-06 and 03-09.
    w = pm.daily_pnl_from_exits(exits, [10.0, -4.0], start="2026-03-02", end="2026-03-13")
    check("window.spans_full_range", len(w) == 10 and w.index[0] == pd.Timestamp("2026-03-02")
          and w.index[-1] == pd.Timestamp("2026-03-13"), f"len={len(w)} first={w.index[0].date()} last={w.index[-1].date()}")
    check("window.zero_filled_edges", w.iloc[0] == 0.0 and w.iloc[-1] == 0.0)
    check("window.total_preserved", abs(w.sum() - 6.0) < 1e-12)

    # Hand Sharpe: values [1, -1, 1, -1, 2] -> mean 0.4, sample std sqrt(1.8) -> *sqrt(252).
    idx = pd.bdate_range("2026-03-02", periods=5)
    v = pd.Series([1.0, -1.0, 1.0, -1.0, 2.0], index=idx)
    expect = 0.4 / np.sqrt(1.8) * np.sqrt(252)
    got = pm.sharpe_from_daily_pnl(v)
    check("sharpe.hand_value", abs(got - expect) < 1e-12, f"got={got:.6f} expect={expect:.6f}")

    # trades wrapper passes the window through
    tr = pd.DataFrame({"exit_time": exits, "pnl_net": [10.0, -4.0]})
    w2 = pm.daily_pnl_from_trades(tr, start="2026-03-02", end="2026-03-13")
    check("trades_wrapper.window", len(w2) == 10)

    print()
    print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    main()
