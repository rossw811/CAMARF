"""
Synthetic verification for portfolio_math.py — the shared daily-P&L-pooling
utility built 2026-07-20 after the Grand Sweep found BUG-D62/D64's
groupby(exit_date)-drops-zero-days convention recurring in FOUR more files
(deflated_sharpe.py, stats.py, cvar.py, fresh_holdout_compare.py).

Proves: (1) daily_pnl_from_trades zero-fills every calendar day, matching a
hand-written resample("1D") reference; (2) it does NOT match a plain
groupby(exit_date) on a fixture with real gaps; (3) sharpe_from_trades
reproduces backtest.py's aggregate_portfolio() convention on the same
fixture (independent hand-written reference, not just checking the module
against itself).
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from portfolio_math import daily_pnl_from_trades, sharpe_from_trades


def _make_gappy_trades() -> pd.DataFrame:
    # 5 trades over a 20-day span, clustered in the first week, then one
    # trade 19 days later -- 15 zero-P&L calendar days in between.
    exit_times = pd.to_datetime([
        "2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-20",
    ])
    pnl = [100.0, -50.0, 75.0, -20.0, 30.0]
    return pd.DataFrame({"exit_time": exit_times, "pnl_net": pnl})


def _old_groupby_sharpe(trades: pd.DataFrame) -> float:
    """Replica of the buggy convention -- kept only to prove the fix changes
    the number in the expected direction, not reintroduced in production."""
    df = trades.copy()
    df["exit_date"] = pd.to_datetime(df["exit_time"]).dt.date
    daily = df.groupby("exit_date")["pnl_net"].sum()
    if len(daily) < 5 or daily.std() == 0:
        return float("nan")
    return float(daily.mean() / daily.std() * np.sqrt(252))


def _reference_resample_sharpe(trades: pd.DataFrame) -> float:
    """Independent hand-written reference for the correct convention."""
    s = pd.Series(trades["pnl_net"].values,
                   index=pd.DatetimeIndex(pd.to_datetime(trades["exit_time"]))).sort_index()
    daily = s.resample("1D").sum()
    if len(daily) < 5 or daily.std() == 0:
        return float("nan")
    return float(daily.mean() / daily.std() * np.sqrt(252))


def main() -> None:
    failures = []
    trades = _make_gappy_trades()

    # 1. Zero-fill correctness: 20-day span (Jan 1 - Jan 20 inclusive) => 20 rows.
    daily = daily_pnl_from_trades(trades)
    if len(daily) != 20:
        failures.append(f"expected 20 zero-filled calendar days, got {len(daily)}")
    if daily.sum() != sum([100.0, -50.0, 75.0, -20.0, 30.0]):
        failures.append(f"zero-filled series total P&L mismatch: {daily.sum()}")
    n_zero_days = (daily == 0.0).sum()
    if n_zero_days != 15:
        failures.append(f"expected 15 zero-P&L days, got {n_zero_days}")

    # 2. Module output matches the independent hand-written reference exactly.
    module_sharpe = sharpe_from_trades(trades)
    ref_sharpe = _reference_resample_sharpe(trades)
    if not np.isclose(module_sharpe, ref_sharpe, atol=1e-10):
        failures.append(f"module Sharpe {module_sharpe} != independent reference {ref_sharpe}")

    # 3. Module output DIFFERS from the old buggy groupby convention on this
    #    gappy fixture (proves the fix actually changes behavior, not a no-op).
    old_sharpe = _old_groupby_sharpe(trades)
    if np.isclose(module_sharpe, old_sharpe, atol=1e-6):
        failures.append(
            f"module Sharpe ({module_sharpe}) suspiciously matches the OLD buggy "
            f"groupby convention ({old_sharpe}) on a fixture with real gaps -- "
            f"fix may not be wired correctly"
        )

    # 4. Edge case: empty trades -> empty series, not a crash.
    empty = pd.DataFrame({"exit_time": pd.to_datetime([]), "pnl_net": []})
    if len(daily_pnl_from_trades(empty)) != 0:
        failures.append("empty trades should produce an empty daily series")
    if not np.isnan(sharpe_from_trades(empty)):
        failures.append("empty trades should produce NaN Sharpe, not a crash")

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("All portfolio_math.py checks passed.")
        print(f"  Gappy fixture: module/reference Sharpe = {module_sharpe:.6f}")
        print(f"  Old buggy groupby convention on same fixture = {old_sharpe:.6f}")
        print(f"  (old convention shrinks N from 20 to 5 zero-P&L-day-dropped rows)")


if __name__ == "__main__":
    main()
